import React, { useMemo, useState } from 'react'
import { AI_COLOR, PERSON_COLOR, AUTOMATION_COLOR, fmtInt, fmtWhen, fmtMs } from './format.js'
import FullRecordSection from './FullRecordSection.jsx'

const KIND_LABEL = {
  prompt: 'prompt', answer: 'answer', command: 'command', result: 'result', file_read: 'read',
  file_write: 'write', file_edit: 'edit', search: 'search', web: 'web', browser: 'browser',
  computer: 'screen', screenshot: 'screenshot', mcp: 'MCP', subagent: 'sub-agent', tool: 'tool',
  notice: 'notice', todo: 'todo', plan: 'plan', job: 'job',
}
const STORY_FILTERS = [
  ['acts', 'Acts', k => ['prompt', 'command', 'file_write', 'file_edit', 'browser', 'computer', 'screenshot', 'web', 'mcp', 'subagent'].includes(k)],
  ['all', 'Everything', () => true],
  ['commands', 'Commands', k => k === 'command'],
  ['files', 'Files', k => ['file_read', 'file_write', 'file_edit'].includes(k)],
]

/**
 * One AI agent session: the agent's own story of it, and what Windows recorded
 * of the same acts. Every Windows record names the rule that matched it to the
 * step (data/ai_agent_links) - there is no score.
 */
export default function SessionDetailPanel({ detail, loading, onOpenProgram, onClose }) {
  const [filter, setFilter] = useState('acts')
  const [openRow, setOpenRow] = useState(null)
  const [allLinks, setAllLinks] = useState(false)
  const story = detail?.story || []
  const shown = useMemo(() => {
    const f = STORY_FILTERS.find(x => x[0] === filter)[2]
    return story.filter(x => f(x.kind))
  }, [story, filter])
  if (loading && !detail) return <div className="detail"><div className="loading-inline" style={{ padding: 20 }}><span className="spinner" />Loading session…</div></div>
  if (!detail || !detail.session) return <div className="detail"><div className="detail-none" style={{ padding: 20 }}>No such session.</div></div>
  const s = detail.session
  const links = detail.links || []
  const linkList = allLinks ? links : links.filter(l => l.source !== 'SRUM').slice(0, 200)
  const bySource = detail.linksBySource || {}
  // A session inside one day shows times; a longer one needs the date too.
  const oneDay = String(s.first_ts || '').slice(0, 10) === String(s.last_ts || '').slice(0, 10)

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">{s.name || s.title || s.session_id}</div>
          <div className="detail-sub">
            <span className="cat-dot" style={{ background: AI_COLOR, marginRight: 6 }} />
            {s.agent}{s.app ? ` (${s.app})` : ''} &middot; {s.user_name} &middot; {fmtWhen(s.first_ts)} &rarr; {fmtWhen(s.last_ts)}
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">Session</div>
          <div className="mace">
            <Row k="Session id" v={s.session_id} />
            <Row k="Recorded title" v={s.title && s.title !== s.name ? s.title : (s.title ? '' : 'none recorded - the name is built from the first request')} />
            <Row k="Project" v={s.project_path} />
            <Row k="Model" v={s.model} />
            <Row k="Approval / sandbox" v={[s.approval_mode, s.sandbox_policy].filter(Boolean).join(' / ')} />
            <Row k="Repository" v={[s.git_origin, s.git_branch, s.git_sha].filter(Boolean).join(' @ ')} />
            <Row k="Process" v={s.pid ? `PID ${s.pid}` : ''} />
            <Row k="Version / entry" v={[s.agent_version, s.entrypoint].filter(Boolean).join(' · ')} />
            <Row k="Counts" v={`${fmtInt(s.prompts)} prompts · ${fmtInt(s.commands)} commands · ${fmtInt(s.file_changes)} file changes`} />
            <Row k="Record" v={s.source_path} />
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">What Windows recorded of this session ({fmtInt(detail.linksTotal)})</div>
          <div className="win-chips">
            {Object.keys(bySource).length ? Object.entries(bySource).map(([k, v]) => (
              <span className="win-chip on" key={k}>{k} {fmtInt(v)}</span>
            )) : <span className="detail-none small">No Windows record matches a step of this session (Prefetch, BAM, 4688, SRUM, USN, browser history).</span>}
          </div>
          {links.length ? (
            <div className="link-list">
              {linkList.map((l, i) => (
                <div className={'link-row' + (oneDay ? '' : ' link-row--dated')} key={i} title={l.rule_text}>
                  <span className="link-t">{oneDay ? fmtWhen(l.ai_ts).slice(11) : fmtWhen(l.ai_ts)}</span>
                  <span className="link-ai" title={l.ai_text}>{l.ai_text}</span>
                  <span className="link-src">{l.source}</span>
                  <span className="link-name" title={l.name}>{l.name}{l.detail ? ` (${l.detail})` : ''}</span>
                  <span className="link-d">{l.delta_s > 0 ? '+' : ''}{l.delta_s}s</span>
                </div>
              ))}
            </div>
          ) : null}
          {links.length && !allLinks ? (
            <button className="link" onClick={() => setAllLinks(true)}>
              {bySource.SRUM ? `show the first ${fmtInt(links.length)} with SRUM's hourly rows${detail.linksTotal > links.length ? ` (of ${fmtInt(detail.linksTotal)})` : ''}` : `show all ${fmtInt(links.length)}`}
            </button>
          ) : null}
          <div className="ov-hint">Each line is one of the agent's steps beside a Windows record of the same act; hover for the rule that matched them. SRUM counts a program per hour, so its rows are shown on request.</div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Programs it ran ({fmtInt((detail.programs || []).length)})</div>
          <div className="prog-list">
            {(detail.programs || []).map((p, i) => (
              <div className="prog-row" key={i} onClick={() => onOpenProgram(p.program)} title="Every run of this program by the agents, and Windows' record of it">
                <span className="prog-dot" style={{ background: AI_COLOR }} />
                <span className="prog-name">{p.program}</span>
                <span className={'win-chip' + (p.prefetch_runs ? ' on' : '')} title="Prefetch run count (all time)">PF {p.prefetch_runs ? fmtInt(p.prefetch_runs) : '–'}</span>
                <span className={'win-chip' + ((p.amcache || []).length ? ' on' : '')} title="AmCache entry">AC</span>
                <span className={'win-chip' + (p.shimcache ? ' on' : '')} title="ShimCache entry">SC</span>
                <span className="prov-count">{fmtInt(p.n)}&times;</span>
              </div>
            ))}
            {!(detail.programs || []).length && <div className="detail-none small">No commands in this session.</div>}
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Files it read or changed ({fmtInt((detail.files || []).length)})</div>
          <div className="file-list">
            {(detail.files || []).map((f, i) => (
              <div className={'file-row' + (f.credential ? ' cred' : '')} key={i} title={f.path}>
                <span className="file-path">{f.path}</span>
                <span className="file-n">{f.changes ? `${fmtInt(f.changes)} change${f.changes === 1 ? '' : 's'}` : ''}{f.changes && f.reads ? ' · ' : ''}{f.reads ? `${fmtInt(f.reads)} read${f.reads === 1 ? '' : 's'}` : ''}</span>
                <span className="file-v" title={(f.versions || []).map(v => `v${v.version} ${v.saved_at} ${v.sha1 || '(no copy: the file was new)'}${v.in_case_path ? ' - in the case' : ''}`).join('\n')}>
                  {(f.versions || []).length ? `${(f.versions || []).length} saved cop${f.versions.length === 1 ? 'y' : 'ies'}` : ''}
                </span>
              </div>
            ))}
          </div>
          <div className="ov-hint">A saved copy is the file as it was before the agent changed it (Claude Code file-history); the AI Agents tab's File Versions table saves it into the case. Credential stores are marked.</div>
        </div>

        {(detail.pages || []).length ? (
          <div className="detail-card">
            <div className="detail-card-title">Pages and screen it drove ({fmtInt(detail.pages.length)})</div>
            <div className="res-list">
              {detail.pages.map((p, i) => <div className="res-row" key={i} title={p.target}>{fmtWhen(p.t).slice(11)} &middot; {p.tool} &middot; {p.target}</div>)}
            </div>
          </div>
        ) : null}

        <div className="detail-card">
          <div className="detail-card-title">The session, step by step ({fmtInt(detail.storyTotal)}{detail.storyTotal > story.length ? `, the first ${fmtInt(story.length)} loaded` : ''})</div>
          <div className="mode-toggle story-filter">
            {STORY_FILTERS.map(([k, label]) => (
              <button key={k} className={filter === k ? 'on' : ''} onClick={() => setFilter(k)}>{label}</button>
            ))}
          </div>
          <div className="story">
            {shown.slice(0, 1500).map((x, i) => {
              const sent = x.kind === 'prompt' && x.role !== 'user' && x.origin
              const open = openRow === i
              return (
                <React.Fragment key={i}>
                  <div className={'story-row story-' + x.role + (x.output || x.origin || x.approval || x.instruction ? ' story-open' : '') + (x.status === 'rejected' ? ' story-refused' : '')}
                    onClick={() => setOpenRow(open ? null : i)} title={x.output || x.origin || x.approval ? 'Show who sent it, who allowed it and what it answered' : undefined}>
                    <span className="story-t" title={x.seq ? `step ${x.seq}` : undefined}>{String(x.t).slice(11, 19)}</span>
                    <span className="story-k" style={{ color: x.role === 'user' ? PERSON_COLOR : (sent ? AUTOMATION_COLOR : (x.role === 'assistant' ? AI_COLOR : undefined)) }}>{sent ? 'sent' : (KIND_LABEL[x.kind] || x.kind)}</span>
                    <span className="story-w" title={x.what}>{x.what}</span>
                    <span className="story-m">{x.kind === 'prompt' && x.turn ? `instruction ${x.turn}` : ''}{x.status === 'rejected' ? 'refused' : ''}{x.program ? x.program : ''}{x.exit !== null && x.exit !== undefined ? ` · exit ${x.exit}` : ''}{x.ms ? ` · ${fmtMs(x.ms)}` : ''}</span>
                  </div>
                  {open ? (
                    <div className="story-more">
                      {x.seq ? <div><span className="mace-k">Order</span> step {x.seq}{x.turn ? `, answering instruction ${x.turn}` : ', before any instruction'}</div> : null}
                      {x.kind !== 'prompt' && x.ordered_by ? <div><span className="mace-k">Ordered by</span> {x.ordered_by}</div> : null}
                      {x.kind !== 'prompt' && x.instruction ? <div><span className="mace-k">Instruction</span> "{x.instruction}"</div> : null}
                      {x.origin ? <div><span className="mace-k">Sent by</span> {x.origin}</div> : null}
                      {x.approval ? <div><span className="mace-k">Allowed</span> {x.approval}</div> : null}
                      {x.output ? <pre className="story-out">{x.output}</pre> : null}
                    </div>
                  ) : null}
                </React.Fragment>
              )
            })}
          </div>
        </div>

        {(detail.processes || []).length ? (
          <div className="detail-card">
            <div className="detail-card-title">Process</div>
            <div className="mace">
              {detail.processes.map((p, i) => <Row key={i} k={`PID ${p.pid}`} v={`${p.kind || ''} · started ${fmtWhen(p.started_at)} · ${p.entrypoint || ''} ${p.version || ''}`} />)}
            </div>
          </div>
        ) : null}

        {(detail.settings || []).length ? (
          <div className="detail-card">
            <div className="detail-card-title">What the agent was allowed and set up to do ({fmtInt(detail.settings.length)})</div>
            <div className="res-list">
              {detail.settings.map((x, i) => <div className="res-row" key={i} title={x.value}>{x.scope} &middot; {x.setting} &middot; {x.value}</div>)}
            </div>
          </div>
        ) : null}

        <FullRecordSection raw={detail?.raw} />
      </div>
    </div>
  )
}

function Row({ k, v }) {
  if (!v) return null
  return <div className="mace-row"><span className="mace-k">{k}</span><span className="mace-v" title={v}>{v}</span><span /></div>
}
