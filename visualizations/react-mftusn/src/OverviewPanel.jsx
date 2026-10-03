import React from 'react'
import { REASONS, REASON_COLOR, fmtInt } from './format.js'

export function ReasonLegend() {
  return (
    <div className="prov-legend">
      {REASONS.map(r => (
        <span className="prov-leg" key={r.key} title={r.desc}><span className="prov-swatch" style={{ background: r.color }} />{r.label}</span>
      ))}
    </div>
  )
}

function Bars({ rows, labelOf, valueOf }) {
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

export default function OverviewPanel({ overview, loading, onOpenInsight }) {
  if (loading && !overview) return <div className="ov"><div className="loading-inline"><span className="spinner" />Loading overview…</div></div>
  const t = overview?.totals || {}
  const a = overview?.anomalies || {}
  const byCat = overview?.byCategory || {}
  const topDirs = overview?.topDirs || []
  const topExts = overview?.topExts || []

  return (
    <div className="ov">
      <div className="ov-title">Overview</div>
      <div className="ov-stats">
        <Tile v={fmtInt(t.files)} l="files" />
        <Tile v={fmtInt(t.directories)} l="directories" />
        <Tile v={fmtInt(t.withEvents)} l="with USN events" />
        <Tile v={fmtInt(t.created)} l="created" />
        <Tile v={fmtInt(t.renamed)} l="renamed" />
        <Tile v={fmtInt(t.dataChanged)} l="data changed" />
      </div>

      <ReasonLegend />

      <div className="ov-card anomaly-card">
        <div className="ov-card-title">Anomalies &amp; anti-forensics</div>
        <div className="anom-grid">
          <Anom d={a.timestompCandidates} l="timestomp candidates" hot={n(a.timestompCandidates) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('timestompCandidates')} />
          <Anom d={a.usnGaps} l="USN journal gaps" hot={n(a.usnGaps) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('usnGaps')} />
          <Anom d={a.deletedButPresent} l="deleted, still in MFT" hot={n(a.deletedButPresent) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('deletedButPresent')} />
          <Anom d={a.ads} l="alternate data streams" hot={n(a.ads) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('ads')} />
        </div>
        <div className="ov-hint">Candidates for review — open one to see the records behind it, then open a file to judge its Standard-Info vs File-Name times.</div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Events by category</div>
        <div className="prov-list">
          {REASONS.map(r => (
            <div className="prov-row" key={r.key}>
              <span className="prov-name"><span className="prov-swatch" style={{ background: r.color }} />{r.label}</span>
              <span className="prov-count">{fmtInt(byCat[r.key] || 0)}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Most active directories</div>
        {topDirs.length ? <Bars rows={topDirs} labelOf={d => d.dir} valueOf={d => d.n} /> : <div className="detail-none small">No data.</div>}
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Most active file types</div>
        {topExts.length ? <Bars rows={topExts} labelOf={e => e.ext} valueOf={e => e.n} /> : <div className="detail-none small">No data.</div>}
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
