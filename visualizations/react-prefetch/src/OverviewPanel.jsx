import React from 'react'
import { LOCATIONS, LOC_COLOR, LOC_LABEL, fmtInt } from './format.js'

export function LocationLegend() {
  return (
    <div className="prov-legend">
      {LOCATIONS.map(l => (
        <span className="prov-leg" key={l.key} title={l.hint}><span className="prov-swatch" style={{ background: l.color }} />{l.label}</span>
      ))}
    </div>
  )
}

export function MiniBars({ rows, labelOf, valueOf, colorOf }) {
  if (!rows.length) return <div className="detail-none small">No data.</div>
  const max = Math.max(1, ...rows.map(valueOf))
  return (
    <div className="mini-bars">
      {rows.map((r, i) => (
        <div className="mini-bar" key={i} title={`${labelOf(r)} — ${fmtInt(valueOf(r))}`}>
          <span className="mini-label">{labelOf(r)}</span>
          <span className="mini-track"><span className="mini-fill" style={{ width: `${(valueOf(r) / max) * 100}%`, background: colorOf ? colorOf(r) : undefined }} /></span>
          <span className="mini-val">{fmtInt(valueOf(r))}</span>
        </div>
      ))}
    </div>
  )
}

export default function OverviewPanel({ overview, loading, onOpenProgram, onOpenInsight }) {
  if (loading && !overview) return <div className="ov"><div className="loading-inline"><span className="spinner" />Loading overview…</div></div>
  const t = overview?.totals || {}
  const ins = overview?.insights || {}
  const volumes = overview?.volumes || []
  const byLoc = overview?.byLocation || []
  const top = overview?.topPrograms || []

  return (
    <div className="ov">
      <div className="ov-title">Overview</div>
      <div className="ov-stats">
        <Tile v={fmtInt(t.programs)} l="distinct programs" />
        <Tile v={fmtInt(t.runs)} l="total runs" />
        <Tile v={fmtInt(t.activeDays)} l="active days" />
        <Tile v={fmtInt(n(ins.singleRun))} l="ran once" />
        <Tile v={fmtInt(n(ins.userTemp))} l="from User/Temp" />
        <Tile v={fmtInt(n(ins.removable))} l="from removable" />
      </div>

      <LocationLegend />

      <div className="ov-card anomaly-card">
        <div className="ov-card-title">Insights</div>
        <div className="anom-grid">
          <Anom d={ins.userTemp} l="ran from User / AppData / Temp" hot={n(ins.userTemp) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('userTemp')} />
          <Anom d={ins.removable} l="ran from removable / other volume" hot={n(ins.removable) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('removable')} />
          <Anom d={ins.singleRun} l="ran only once" hot={false}
            onOpen={() => onOpenInsight && onOpenInsight('singleRun')} />
          <Anom d={ins.maxRuns} l="most runs (single program)" hot={false} />
        </div>
        <div className="ov-hint">Programs run from User/Temp or a removable volume, and one-off runs, are the first things to check.</div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Most-run programs</div>
        <div className="prog-list">
          {top.length ? top.map((p, i) => (
            <div className="prog-row" key={i} onClick={() => onOpenProgram && onOpenProgram(p.filename)} title="Open program profile">
              <span className="prog-dot" style={{ background: LOC_COLOR[p.location] }} />
              <span className="prog-name">{p.exe}</span>
              <span className="prov-count">{fmtInt(p.runCount)}&times;</span>
            </div>
          )) : <div className="detail-none small">No data.</div>}
        </div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">By run location</div>
        <MiniBars rows={byLoc} labelOf={l => LOC_LABEL[l.loc]} valueOf={l => l.n} colorOf={l => LOC_COLOR[l.loc]} />
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Volumes (execution device history)</div>
        <div className="vol-list">
          {volumes.length ? volumes.map((v, i) => (
            <div className="vol-row" key={i}>
              <span className="vol-name">
                <span className="vol-tag" style={{ background: v.type === 'removable' ? '#fbbf24' : '#94a3b8' }}>{v.type}</span>
                {v.label || '(no label)'}{v.serial ? <span className="vol-sn"> · {v.serial}</span> : null}
              </span>
              <span className="prov-count">{fmtInt(v.n)}</span>
            </div>
          )) : <div className="detail-none small">No volume data.</div>}
        </div>
      </div>
    </div>
  )
}

function Tile({ v, l }) { return <div className="ov-tile"><span>{v}</span><label>{l}</label></div> }
// An insight is {count, subjects, truncated}; `n` also tolerates the bare
// integer the bridges used to return, so a stale bundle degrades to the old
// read-only tile instead of rendering "[object Object]".
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
