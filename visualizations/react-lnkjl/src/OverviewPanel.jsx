import React from 'react'
import { SOURCES, fmtInt } from './format.js'

export function SourceLegend() {
  return (
    <div className="prov-legend">
      {SOURCES.map(s => (
        <span className="prov-leg" key={s.key}><span className="prov-swatch" style={{ background: s.color }} />{s.label}</span>
      ))}
    </div>
  )
}

export function MiniBars({ rows, labelOf, valueOf }) {
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

function driveTag(t) {
  const u = (t || '').toUpperCase()
  if (u.includes('REMOV')) return { t: 'removable', c: '#fbbf24' }
  if (u.includes('REMOTE') || u.includes('NETWORK')) return { t: 'network', c: '#22d3ee' }
  if (u.includes('FIXED')) return { t: 'fixed', c: '#94a3b8' }
  return { t: 'unknown', c: '#64748b' }
}

export default function OverviewPanel({ overview, loading, onOpenInsight }) {
  if (loading && !overview) return <div className="ov"><div className="loading-inline"><span className="spinner" />Loading overview…</div></div>
  const t = overview?.totals || {}
  const ins = overview?.insights || {}
  const volumes = overview?.volumes || []
  const byApp = overview?.byApp || []
  const topDirs = overview?.topDirs || []
  const topExts = overview?.topExts || []

  return (
    <div className="ov">
      <div className="ov-title">Overview</div>
      <div className="ov-stats">
        <Tile v={fmtInt(t.targets)} l="distinct targets" />
        <Tile v={fmtInt(t.records)} l="open records" />
        <Tile v={fmtInt(t.lnk)} l="LNK" />
        <Tile v={fmtInt(t.auto)} l="auto jump list" />
        <Tile v={fmtInt(t.custom)} l="custom jump list" />
        <Tile v={fmtInt(n(ins.externalVolumes))} l="external volumes" />
      </div>

      <SourceLegend />

      <div className="ov-card anomaly-card">
        <div className="ov-card-title">Insights</div>
        <div className="anom-grid">
          <Anom d={ins.removable} l="opens from removable media" hot={n(ins.removable) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('removable')} />
          <Anom d={ins.network} l="opens from network drives" hot={n(ins.network) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('network')} />
          <Anom d={ins.tempDownloads} l="Temp / Downloads / AppData targets" hot={n(ins.tempDownloads) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('tempDownloads')} />
          <Anom d={ins.externalVolumes} l="distinct external volumes" hot={n(ins.externalVolumes) > 0} />
        </div>
        <div className="ov-hint">Every open leaves a volume serial &mdash; the Volumes card below is a device-history trail.</div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Volumes (device history)</div>
        <div className="vol-list">
          {volumes.length ? volumes.map((v, i) => {
            const tag = driveTag(v.driveType)
            return (
              <div className="vol-row" key={i}>
                <span className="vol-name">
                  <span className="vol-tag" style={{ background: tag.c }}>{tag.t}</span>
                  {v.label || '(no label)'}{v.serial ? <span className="vol-sn"> · {v.serial}</span> : null}
                </span>
                <span className="prov-count">{fmtInt(v.n)}</span>
              </div>
            )
          }) : <div className="detail-none small">No volume data.</div>}
        </div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">By application</div>
        <MiniBars rows={byApp} labelOf={a => a.app} valueOf={a => a.n} />
      </div>
      <div className="ov-card">
        <div className="ov-card-title">Most opened directories</div>
        <MiniBars rows={topDirs} labelOf={d => d.dir} valueOf={d => d.n} />
      </div>
      <div className="ov-card">
        <div className="ov-card-title">Most opened file types</div>
        <MiniBars rows={topExts} labelOf={e => e.ext} valueOf={e => e.n} />
      </div>
    </div>
  )
}

function Tile({ v, l }) { return <div className="ov-tile"><span>{v}</span><label>{l}</label></div> }
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
