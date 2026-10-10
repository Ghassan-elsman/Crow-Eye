import React from 'react'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, Tooltip,
} from 'chart.js'
import { fmtInt, fmtCompact, fmtBytes, fmtDuration, fmtDay, PROVIDERS, PROVIDER_LABEL } from './format.js'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, Tooltip)

const NET_SENT = '#6366f1', NET_RECV = '#22d3ee'

// One stacked dataset per provider (provider = colour everywhere).
function stackedByProvider(rows, labelOf) {
  return {
    labels: rows.map(labelOf),
    datasets: PROVIDERS.map(p => ({
      label: p.label, backgroundColor: p.color, borderRadius: 1, borderWidth: 0,
      data: rows.map(r => (r.counts && r.counts[p.key]) || 0),
    })),
  }
}
const stackedOpts = {
  indexAxis: 'y', responsive: true, maintainAspectRatio: false, animation: false,
  plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.x)}` } } },
  scales: {
    x: { stacked: true, ticks: { color: '#94a3b8', font: { size: 12 }, callback: (v) => fmtInt(v) }, grid: { color: 'rgba(99,102,241,0.10)' } },
    y: { stacked: true, ticks: { color: '#cbd5e1', font: { size: 12 } }, grid: { display: false } },
  },
}

export function ProviderLegend() {
  return (
    <div className="prov-legend">
      {PROVIDERS.map(p => (
        <span className="prov-leg" key={p.key}><span className="prov-swatch" style={{ background: p.color }} />{p.label}</span>
      ))}
    </div>
  )
}

export default function OverviewPanel({ overview, loading, onOpenApp, onOpenInsight }) {
  if (loading && !overview) return <div className="ov"><div className="loading-inline"><span className="spinner" />Loading overview…</div></div>
  const t = overview?.totals || {}
  const topApps = overview?.topApps || []
  const byUser = overview?.byUser || []
  const providers = overview?.providerTotals || {}
  const networkByDay = overview?.networkByDay || []
  const topNetworkApps = overview?.topNetworkApps || []
  const ins = overview?.insights || {}

  const netData = {
    labels: networkByDay.map(d => d.day),
    datasets: [
      { label: 'Sent', backgroundColor: NET_SENT, borderWidth: 0, data: networkByDay.map(d => d.sent) },
      { label: 'Received', backgroundColor: NET_RECV, borderWidth: 0, data: networkByDay.map(d => d.received) },
    ],
  }
  const netOpts = {
    responsive: true, maintainAspectRatio: false, animation: false,
    plugins: { legend: { display: false },
      tooltip: { callbacks: { title: (i) => fmtDay(i[0].label), label: (c) => `${c.dataset.label}: ${fmtBytes(c.parsed.y)}` } } },
    scales: {
      x: { stacked: true, ticks: { display: false }, grid: { display: false } },
      y: { stacked: true, ticks: { color: '#94a3b8', font: { size: 11 }, callback: (v) => fmtBytes(v) }, grid: { color: 'rgba(99,102,241,0.10)' } },
    },
  }

  return (
    <div className="ov">
      <div className="ov-title">Overview</div>
      <div className="ov-stats">
        <Tile v={fmtInt(t.activeDays)} l="active days" />
        <Tile v={fmtInt(t.apps)} l="distinct apps" />
        <Tile v={fmtBytes(t.bytesSent)} l="sent" />
        <Tile v={fmtBytes(t.bytesReceived)} l="received" />
        <Tile v={fmtCompact(t.cpu)} l="CPU cycles" title={fmtInt(t.cpu)} />
        <Tile v={fmtDuration(t.presenceSecs)} l="user presence" />
      </div>

      <ProviderLegend />

      <div className="ov-card anomaly-card">
        <div className="ov-card-title">Insights</div>
        <div className="anom-grid">
          <Anom d={ins.netSkew} l="sent far more than received" hot={n(ins.netSkew) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('netSkew')} />
          <Anom d={ins.oneDay} l="seen on one day only" hot={false}
            onOpen={() => onOpenInsight && onOpenInsight('oneDay')} />
          <Anom d={ins.busiestApp} l="days for the busiest app" hot={false} />
          <Anom d={ins.users} l="distinct user accounts" hot={false} />
        </div>
        <div className="ov-hint">
          Upload-shaped traffic and one-off executions are the two leads SRUM gives
          on its own. SRUM records foreground time for only {fmtInt(t.appsWithFocus)} of
          the {fmtInt(t.apps)} applications it recorded here, so a missing focus time is
          a gap in the artifact, not evidence that something ran unattended.
        </div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Network activity</div>
        <div className="prov-legend" style={{ marginBottom: 8 }}>
          <span className="prov-leg"><span className="prov-swatch" style={{ background: NET_SENT }} />Sent</span>
          <span className="prov-leg"><span className="prov-swatch" style={{ background: NET_RECV }} />Received</span>
        </div>
        <div className="chart-box" style={{ height: 120 }}>
          {networkByDay.length ? <Chart type="bar" data={netData} options={netOpts} />
            : <div className="detail-none small">No network records.</div>}
        </div>
        <div className="ov-hint">Bytes sent / received per day.</div>
        {topNetworkApps.length > 0 && (
          <div className="net-apps">
            {topNetworkApps.map(a => (
              <div className={'net-app' + (onOpenApp ? ' net-app--open' : '')} key={a.app}
                title={onOpenApp ? 'Open application profile' : a.app}
                onClick={() => onOpenApp && onOpenApp(a.app)}>
                <span className="net-app-name" title={a.app}>{a.app}</span>
                <span className="net-app-vals">
                  <span style={{ color: NET_SENT }}>&#9650; {fmtBytes(a.sent)}</span>
                  <span style={{ color: NET_RECV }}>&#9660; {fmtBytes(a.received)}</span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Most active applications</div>
        <div className="chart-box" style={{ height: Math.max(100, topApps.length * 24) }}>
          {topApps.length ? <Chart type="bar" data={stackedByProvider(topApps, a => a.app)} options={stackedOpts} />
            : <div className="detail-none small">No data.</div>}
        </div>
        <div className="ov-hint">Record count per app, split by provider.</div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Activity by user</div>
        <div className="chart-box" style={{ height: Math.max(80, byUser.length * 28) }}>
          {byUser.length ? <Chart type="bar" data={stackedByProvider(byUser, u => u.user)} options={stackedOpts} />
            : <div className="detail-none small">No data.</div>}
        </div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Records by provider</div>
        <div className="prov-list">
          {PROVIDERS.map(p => (
            <div className="prov-row" key={p.key}>
              <span className="prov-name"><span className="prov-swatch" style={{ background: p.color }} />{p.label}</span>
              <span className="prov-count">{fmtInt(providers[p.key] || 0)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Tile({ v, l, title }) {
  return <div className="ov-tile" title={title}><span>{v}</span><label>{l}</label></div>
}

// An insight is {count, subjects, truncated}; `n` also tolerates the bare
// integer, so a stale bundle degrades to a read-only tile rather than
// rendering "[object Object]".
function n(d) { return (d && typeof d === 'object') ? (d.count || 0) : (d || 0) }

function Anom({ d, l, hot, onOpen }) {
  const can = !!onOpen && (d && typeof d === 'object') && (d.subjects || []).length > 0
  return (
    <div className={'anom' + (hot ? ' hot' : '') + (can ? ' anom--open' : '')}
      title={can ? 'Show the records behind this' : undefined}
      onClick={() => can && onOpen()}>
      <span>{fmtInt(n(d))}</span><label>{l}</label>
    </div>
  )
}
