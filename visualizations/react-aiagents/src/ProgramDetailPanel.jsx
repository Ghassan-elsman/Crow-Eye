import React from 'react'
import { AI_COLOR, fmtInt, fmtWhen, fmtMs } from './format.js'
import FullRecordSection from './FullRecordSection.jsx'

/**
 * One program, every time an AI agent started it, and what Windows recorded of
 * it: the Prefetch runs that fall inside an agent's command, BAM, 4688, SRUM
 * (each link naming its rule), and what the system knows of the program with
 * no time attached (Prefetch run count, AmCache, ShimCache).
 */
export default function ProgramDetailPanel({ detail, loading, onOpenSession, onClose }) {
  if (loading && !detail) return <div className="detail"><div className="loading-inline" style={{ padding: 20 }}><span className="spinner" />Loading program…</div></div>
  if (!detail || !detail.program) return <div className="detail"><div className="detail-none" style={{ padding: 20 }}>No such program.</div></div>
  const pr = detail.presence || {}
  const links = (detail.links || []).filter(l => l.source !== 'SRUM')
  const srum = (detail.links || []).length - links.length
  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">{detail.program}</div>
          <div className="detail-sub">
            <span className="cat-dot" style={{ background: AI_COLOR, marginRight: 6 }} />
            started by {fmtInt(detail.runsTotal)} agent command{detail.runsTotal === 1 ? '' : 's'} in {fmtInt(detail.sessions)} session{detail.sessions === 1 ? '' : 's'}
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>
      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">What the system knows of it</div>
          <div className="mace">
            <div className="mace-row"><span className="mace-k">Prefetch</span><span>{pr.prefetch_runs ? `${fmtInt(pr.prefetch_runs)} runs, last ${fmtWhen(pr.prefetch_last)}` : 'no Prefetch file'}</span><span /></div>
            <div className="mace-row"><span className="mace-k">AmCache</span><span>{(pr.amcache || []).length ? (pr.amcache || []).map(a => a.path).join(' · ') : 'no entry'}</span><span /></div>
            <div className="mace-row"><span className="mace-k">ShimCache</span><span>{pr.shimcache ? `${fmtInt(pr.shimcache)} entr${pr.shimcache === 1 ? 'y' : 'ies'}` : 'no entry'}</span><span /></div>
          </div>
          <div className="ov-hint">Shell builtins and scripts never get a Prefetch file; a program that ran through WSL or a container is recorded under its host process.</div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Windows' record of the agent's runs ({fmtInt(links.length)}{srum ? `, and ${fmtInt(srum)} SRUM hours` : ''})</div>
          <div className="link-list">
            {links.slice(0, 300).map((l, i) => (
              <div className="link-row link-row--prog" key={i} title={l.rule_text} onClick={() => onOpenSession(`${l.ai_agent}|${l.ai_session}`)}>
                <span className="link-t">{fmtWhen(l.ai_ts)}</span>
                <span className="link-src">{l.source}</span>
                <span className="link-name" title={l.name}>{l.name}</span>
                <span className="link-d">{l.delta_s > 0 ? '+' : ''}{l.delta_s}s</span>
              </div>
            ))}
            {!links.length && <div className="detail-none small">No Prefetch, BAM or 4688 record falls inside one of the agent's commands.</div>}
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Every run by an agent ({fmtInt(detail.runsTotal)})</div>
          <div className="story story--dated">
            {(detail.runs || []).map((r, i) => (
              <div className="story-row story-assistant story-open" key={i} onClick={() => onOpenSession(r.session)} title="Open the session">
                <span className="story-t">{fmtWhen(r.t)}</span>
                <span className="story-k" style={{ color: AI_COLOR }}>{r.agent}</span>
                <span className="story-w" title={r.what}>{r.what}</span>
                <span className="story-m">{r.exit !== null && r.exit !== undefined ? `exit ${r.exit}` : ''}{r.ms ? ` · ${fmtMs(r.ms)}` : ''}</span>
              </div>
            ))}
          </div>
        </div>
        <FullRecordSection records={detail?.records} />
      </div>
    </div>
  )
}
