import React from 'react'
import { SOURCES, SOURCE_COLOR, SOURCE_LABEL, fmtInt } from './format.js'

export function SourceLegend() {
  return (
    <div className="prov-legend">
      {SOURCES.map(s => (
        <span className="prov-leg" key={s.key} title={s.hint}><span className="prov-swatch" style={{ background: s.color }} />{s.label}</span>
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

export default function OverviewPanel({ overview, loading, onOpenInsight, emptyNotes, sourceErrors }) {
  if (loading && !overview) return <div className="ov"><div className="loading-inline"><span className="spinner" />Loading overview…</div></div>
  const t = overview?.totals || {}
  const ins = overview?.insights || {}
  const volumes = overview?.volumes || []
  const bySrc = overview?.bySource || []
  const places = overview?.topPlaces || []
  const files = overview?.topFiles || []

  return (
    <div className="ov">
      <div className="ov-title">Overview</div>
      <div className="ov-stats">
        <Tile v={fmtInt(t.items)} l="items" />
        <Tile v={fmtInt(t.targets)} l="distinct targets" />
        <Tile v={fmtInt(t.sources)} l="active sources" />
        <Tile v={fmtInt(t.activeDays)} l="active days" />
        <Tile v={fmtInt(n(ins.network))} l="network targets" />
        <Tile v={fmtInt(n(ins.removable))} l="removable targets" />
      </div>

      <SourceLegend />

      <div className="ov-card anomaly-card">
        <div className="ov-card-title">Insights</div>
        <div className="anom-grid">
          <Anom d={ins.network} l="targets on a network share" hot={n(ins.network) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('network')} />
          <Anom d={ins.removable} l="targets on removable / other volume" hot={n(ins.removable) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('removable')} />
          <Anom d={ins.macMismatch} l="shellbag FAT time ≠ registry write" hot={n(ins.macMismatch) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('macMismatch')} />
          <Anom d={ins.users} l="distinct users" hot={false} />
        </div>
        <div className="ov-hint">Network and removable targets, and shellbags whose embedded folder time disagrees with the registry write, are the first things to check.</div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">By source</div>
        <MiniBars rows={bySrc} labelOf={s => SOURCE_LABEL[s.source]} valueOf={s => s.n} colorOf={s => SOURCE_COLOR[s.source]} />
        {/* A source at 0 says why, and a source that could not be read says
            so - neither is the same as "nothing happened". */}
        {Object.entries(sourceErrors || {}).map(([k, v]) => (
          <div className="empty-src-note" key={'e' + k}><b>{SOURCE_LABEL[k] || k}: could not be read.</b> {v}</div>
        ))}
        {Object.entries(emptyNotes || {}).map(([k, v]) => (
          <div className="empty-src-note" key={'n' + k}><b>{SOURCE_LABEL[k] || k}: 0.</b> {v}</div>
        ))}
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Most-visited places</div>
        <MiniBars rows={places} labelOf={p => p.place} valueOf={p => p.n} />
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Most-referenced files</div>
        <MiniBars rows={files} labelOf={f => f.file} valueOf={f => f.n} />
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Volumes &amp; shares (device history)</div>
        <div className="vol-list">
          {volumes.length ? volumes.map((v, i) => (
            <div className="vol-row" key={i}>
              <span className="vol-name">
                <span className="vol-tag" style={{ background: v.type === 'removable' ? '#fbbf24' : v.type === 'network' ? '#22d3ee' : '#94a3b8' }}>{v.type}</span>
                {v.label || '(no label)'}
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
