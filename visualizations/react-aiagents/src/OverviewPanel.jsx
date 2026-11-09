import React from 'react'
import { SERIES, AI_COLOR, fmtInt } from './format.js'

export function SeriesLegend() {
  return (
    <div className="prov-legend">
      {SERIES.map(s => (
        <span className="prov-leg" key={s.key} title={s.hint}><span className="prov-swatch" style={{ background: s.color }} />{s.label}</span>
      ))}
    </div>
  )
}

export function MiniBars({ rows, labelOf, valueOf, colorOf, onOpen, titleOf }) {
  if (!rows.length) return <div className="detail-none small">No data.</div>
  const max = Math.max(1, ...rows.map(valueOf))
  return (
    <div className="mini-bars">
      {rows.map((r, i) => (
        <div className={'mini-bar' + (onOpen ? ' mini-bar--open' : '')} key={i}
          title={titleOf ? titleOf(r) : `${labelOf(r)} — ${fmtInt(valueOf(r))}`}
          onClick={() => onOpen && onOpen(r)}>
          <span className="mini-label">{labelOf(r)}</span>
          <span className="mini-track"><span className="mini-fill" style={{ width: `${(valueOf(r) / max) * 100}%`, background: colorOf ? colorOf(r) : AI_COLOR }} /></span>
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
  const counts = overview?.counts || {}
  const agents = overview?.byAgent || []
  const top = overview?.topPrograms || []

  return (
    <div className="ov">
      <div className="ov-title">Overview</div>
      <div className="ov-stats">
        <Tile v={fmtInt(t.sessions)} l="sessions" />
        <Tile v={fmtInt(t.prompts)} l="prompts typed" />
        <Tile v={fmtInt(t.commands)} l="commands run" />
        <Tile v={fmtInt(n(ins.distinctPrograms))} l="programs started" />
        <Tile v={fmtInt(t.files)} l="files changed" />
        <Tile v={fmtInt(t.pages)} l="browser / screen" />
        <Tile v={fmtInt(counts.ai_agent_file_versions)} l="saved file copies" />
        <Tile v={fmtInt(counts.ai_agent_processes)} l="processes" />
        <Tile v={fmtInt(t.days)} l="active days" />
      </div>

      <SeriesLegend />

      <div className="ov-card anomaly-card">
        <div className="ov-card-title">Insights</div>
        <div className="anom-grid">
          <Anom d={ins.failedCommands} l="commands that failed (exit code)" hot={false}
            onOpen={() => onOpenInsight('failedCommands')} />
          <Anom d={ins.credentialFiles} l="credential stores read or changed" hot={n(ins.credentialFiles) > 0}
            onOpen={() => onOpenInsight('credentialFiles')} />
          <Anom d={ins.bypassSessions} l="sessions with approvals off" hot={false}
            onOpen={() => onOpenInsight('bypassSessions')} />
          <Anom d={ins.notFromPerson} l="prompts nobody typed (scheduled, another agent, a program)" hot={false}
            onOpen={() => onOpenInsight('notFromPerson')} />
          <Anom d={ins.refusedCalls} l="calls refused before they ran" hot={false}
            onOpen={() => onOpenInsight('refusedCalls')} />
          <Anom d={ins.goneTranscripts} l="sessions whose transcript is gone" hot={false}
            onOpen={() => onOpenInsight('goneTranscripts')} />
        </div>
        <div className="ov-hint">An agent that read a credential store, or ran with every approval off, is the first thing to check; a transcript that is gone while its prompts remain is the second.</div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">Programs the agents started</div>
        <div className="prog-list">
          {top.length ? top.map((p, i) => (
            <div className="prog-row" key={i} onClick={() => onOpenProgram(p.program)}
              title={`Started by ${fmtInt(p.n)} agent commands. Prefetch records ${fmtInt(p.prefetchRuns)} runs; AmCache ${p.amcache ? 'knows it' : 'has no entry'}. Open for every run and Windows' record of it.`}>
              <span className="prog-dot" style={{ background: AI_COLOR }} />
              <span className="prog-name">{p.program}</span>
              <span className={'win-chip' + (p.prefetchRuns ? ' on' : '')} title="Prefetch">PF {p.prefetchRuns ? fmtInt(p.prefetchRuns) : '–'}</span>
              <span className="prov-count">{fmtInt(p.n)}&times;</span>
            </div>
          )) : <div className="detail-none small">No commands.</div>}
        </div>
      </div>

      <div className="ov-card">
        <div className="ov-card-title">By agent</div>
        <div className="vol-list">
          {agents.length ? agents.map((a, i) => (
            <div className="vol-row" key={i}>
              <span className="vol-name">{a.agent}</span>
              <span className="prov-count" title="sessions / commands / file changes">{fmtInt(a.sessions)} &middot; {fmtInt(a.commands)} &middot; {fmtInt(a.file_changes)}</span>
            </div>
          )) : <div className="detail-none small">No agents.</div>}
        </div>
        <div className="ov-hint">sessions &middot; commands &middot; file changes</div>
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
