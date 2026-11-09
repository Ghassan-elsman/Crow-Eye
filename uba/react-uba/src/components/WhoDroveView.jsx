import { useEffect, useMemo, useState } from 'react'
import { DRIVERS, DRIVER_STYLE, APP_STATE_STYLE } from '../styles/tokens.js'

// Who drove it: what a person, a person remotely, a program by itself, a
// script or an AI agent did - per day and hour, per AI agent session, per
// program's keyboard, mouse and focus, and per person. Everything that shows a
// number opens the activities or the rows behind it (building-a-visualization:
// every clickable surface opens something).
//
// Data: getSummary's by_driver / by_app_state / driver_heatmap (event_store),
// getDriversByPerson, and two evidence readers that run off the GUI thread:
// getAgentSessions (ai_agents.db) and getInputLayer (SRUM App Timeline).

const PAGE_DAYS = 183
const fmt = (n) => (n || 0).toLocaleString()
const pct = (n, t) => (t ? Math.round((100 * n) / t) : 0)
const hh = (s) => String(Math.floor(s / 3600)).padStart(2, '0') + ':' + String(Math.floor((s % 3600) / 60)).padStart(2, '0')
const secOfDay = (ts) => {
  const t = String(ts || '')
  return (+t.slice(11, 13) || 0) * 3600 + (+t.slice(14, 16) || 0) * 60 + (+t.slice(17, 19) || 0)
}
const dur = (s) => (s >= 3600 ? `${(s / 3600).toFixed(1)} h` : s >= 60 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`)
const base = (p) => String(p || '').replace(/[\\/]+$/, '').split(/[\\/]/).pop()

function daysBetween(a, b) {
  const out = []
  const d = new Date(a + 'T00:00:00Z')
  const end = new Date(b + 'T00:00:00Z')
  for (let i = 0; d <= end && i < 4000; i++) {
    out.push(d.toISOString().slice(0, 10))
    d.setUTCDate(d.getUTCDate() + 1)
  }
  return out
}

function Section({ title, sub, right, children }) {
  return (
    <section className="wd-section">
      <div className="wd-head">
        <div>
          <h3>{title}</h3>
          {sub && <p className="wd-sub">{sub}</p>}
        </div>
        {right}
      </div>
      {children}
    </section>
  )
}

function Empty({ text }) {
  return <div className="wd-empty">{text}</div>
}

// ---------------------------------------------------------------- tiles
function DriverTiles({ summary, onOpen }) {
  const by = Object.fromEntries((summary.by_driver || []).map((r) => [r.driver, r.events]))
  const states = Object.fromEntries((summary.by_app_state || []).map((r) => [r.app_state, r.events]))
  const total = DRIVERS.reduce((a, k) => a + (by[k] || 0), 0)
  return (
    <>
      <div className="wd-tiles">
        {DRIVERS.map((k) => {
          const s = DRIVER_STYLE[k]
          const n = by[k] || 0
          return (
            <button key={k} className="wd-tile" disabled={!n} onClick={() => onOpen({ drivers: [k] })}
              title={n ? `Open the ${fmt(n)} activities: ${s.label}` : 'None in this view'}>
              <span className="wd-tile-bar" style={{ background: s.color }} />
              <span className="wd-tile-n" style={{ color: n ? s.color : undefined }}>{fmt(n)}</span>
              <span className="wd-tile-l">{s.label}</span>
              <span className="wd-tile-p">{pct(n, total)}%</span>
            </button>
          )
        })}
      </div>
      <div className="wd-share" role="img" aria-label="Share of activities by who drove them">
        {DRIVERS.map((k) => (by[k] ? (
          <button key={k} className="wd-share-seg" style={{ flexGrow: by[k], background: DRIVER_STYLE[k].color }}
            title={`${DRIVER_STYLE[k].label}: ${fmt(by[k])} (${pct(by[k], total)}%)`}
            onClick={() => onOpen({ drivers: [k] })} />
        ) : null))}
      </div>
      <div className="wd-states">
        {['foreground', 'background'].map((k) => (
          <button key={k} className="wd-state" disabled={!states[k]} onClick={() => onOpen({ app_states: [k] })}
            style={{ borderColor: APP_STATE_STYLE[k].color }}>
            <b style={{ color: APP_STATE_STYLE[k].color }}>{fmt(states[k] || 0)}</b> program activities {APP_STATE_STYLE[k].label.toLowerCase()}
          </button>
        ))}
        <span className="wd-note">In front or behind is told only for a program's own activity, from Windows' focus record.</span>
      </div>
    </>
  )
}

// ---------------------------------------------------------------- days x drivers
function DayStripByDriver({ summary, day, onDay }) {
  const { days, cells, rowMax } = useMemo(() => {
    const per = {}
    const rowMax = {}
    for (const c of summary.driver_heatmap || []) {
      const k = c.day + '|' + c.driver
      per[k] = (per[k] || 0) + c.events
    }
    for (const [k, n] of Object.entries(per)) {
      const d = k.split('|')[1]
      rowMax[d] = Math.max(rowMax[d] || 0, n)
    }
    const all = Object.keys(per).map((k) => k.split('|')[0]).sort()
    const days = all.length ? daysBetween(all[0], all[all.length - 1]) : []
    return { days, cells: per, rowMax }
  }, [summary])
  const [page, setPage] = useState(0)
  useEffect(() => { setPage(0) }, [days.length])
  if (!days.length) return <Empty text="No activity with a time in this view." />
  const pages = Math.max(1, Math.ceil(days.length / PAGE_DAYS))
  const endIdx = days.length - page * PAGE_DAYS
  const shown = days.slice(Math.max(0, endIdx - PAGE_DAYS), endIdx)
  const rows = DRIVERS.filter((k) => rowMax[k])
  return (
    <div className="wd-strip">
      <div className="wd-strip-nav">
        <button disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>‹ Earlier</button>
        <span>{shown[0]} — {shown[shown.length - 1]} · {shown.length} days</span>
        <button disabled={page === 0} onClick={() => setPage(page - 1)}>Later ›</button>
      </div>
      {rows.map((k) => (
        <div className="wd-strip-row" key={k}>
          <span className="wd-strip-label"><i style={{ background: DRIVER_STYLE[k].color }} />{DRIVER_STYLE[k].short}</span>
          <div className="wd-strip-cells" style={{ gridTemplateColumns: `repeat(${shown.length}, minmax(0, 1fr))` }}>
            {shown.map((d) => {
              const n = cells[d + '|' + k] || 0
              const a = n ? 0.18 + 0.82 * Math.sqrt(n / rowMax[k]) : 0
              return (
                <button key={d} className={'wd-cell' + (d === day ? ' sel' : '')}
                  style={n ? { background: DRIVER_STYLE[k].color, opacity: a } : null}
                  title={`${d}: ${fmt(n)} ${DRIVER_STYLE[k].label}`} onClick={() => onDay(d)} />
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}

function HourBars({ summary, day, onOpen }) {
  const hours = useMemo(() => {
    const h = Array.from({ length: 24 }, () => ({}))
    for (const c of summary.driver_heatmap || []) {
      if (c.day === day) h[c.hour][c.driver] = (h[c.hour][c.driver] || 0) + c.events
    }
    return h
  }, [summary, day])
  const max = Math.max(1, ...hours.map((h) => Object.values(h).reduce((a, b) => a + b, 0)))
  const total = hours.reduce((a, h) => a + Object.values(h).reduce((x, y) => x + y, 0), 0)
  if (!total) return <Empty text={`Nothing with a time on ${day}.`} />
  return (
    <div className="wd-hours">
      {hours.map((h, i) => (
        <div className="wd-hour" key={i}>
          <div className="wd-hour-stack">
            {DRIVERS.filter((k) => h[k]).map((k) => (
              <button key={k} className="wd-hour-seg" style={{ height: `${(100 * h[k]) / max}%`, background: DRIVER_STYLE[k].color }}
                title={`${day} ${String(i).padStart(2, '0')}:00 — ${fmt(h[k])} ${DRIVER_STYLE[k].label}`}
                onClick={() => onOpen({ drivers: [k], start: `${day} ${String(i).padStart(2, '0')}:00:00`, end: `${day} ${String(i).padStart(2, '0')}:59:59` })} />
            ))}
          </div>
          <span className="wd-hour-l">{i % 3 === 0 ? String(i).padStart(2, '0') : ''}</span>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------- AI agent sessions
const MARK = {
  request: { label: 'The person asked', cls: 'm-request' },
  instruction: { label: 'The main agent instructed a sub-agent', cls: 'm-instruction' },
  command: { label: 'The agent ran a command', cls: 'm-command' },
  own_command: { label: 'The person ran a command', cls: 'm-own' },
  file: { label: 'The agent changed a file', cls: 'm-file' },
  notice: { label: 'A background task finished (or the program wrote a notice)', cls: 'm-notice' },
  sent: { label: 'A prompt nobody typed: a scheduled task, a program (claude -p), the program resuming', cls: 'm-sent' },
  peer: { label: 'Another agent session sent a message', cls: 'm-peer' },
}

function AgentSessions({ day, callAsync, onRows }) {
  const [data, setData] = useState(null)
  useEffect(() => {
    let live = true
    setData(null)
    callAsync('getAgentSessions', JSON.stringify({ start: `${day} 00:00:00`, end: `${day} 23:59:59` }))
      .then((r) => { if (live) setData(r || { available: false, reason: 'The AI agent sessions could not be read.' }) })
    return () => { live = false }
  }, [day, callAsync])
  if (!data) return <div className="wd-loading">Reading the AI agent sessions…</div>
  if (!data.available || !data.sessions.length) return <Empty text={data.reason || 'No AI agent session on this day.'} />
  const parents = new Set(data.sessions.map((s) => s.session_id))
  return (
    <div className="wd-lanes">
      <div className="wd-axis">{[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => <span key={h} style={{ left: `${(100 * h) / 24}%` }}>{String(h).padStart(2, '0')}</span>)}</div>
      {data.sessions.map((s) => {
        const a = s.first_ts && s.first_ts.slice(0, 10) === day ? secOfDay(s.first_ts) : 0
        const b = s.last_ts && s.last_ts.slice(0, 10) === day ? secOfDay(s.last_ts) : 86400
        const sub = s.parent && parents.has(s.parent)
        return (
          <div className={'wd-lane' + (sub ? ' sub' : '')} key={s.session_id}>
            <button className="wd-lane-label" onClick={() => onRows({ db: 'ai_agents', table: 'ai_agent_sessions', rowids: [s.rowid], title: `${s.agent} session ${s.session_id}` })}
              title={`${s.agent} · ${s.project}\n${s.model || ''} ${s.approval_mode ? '· approval: ' + s.approval_mode : ''}\n${fmt(s.prompts)} requests · ${fmt(s.commands)} commands · ${fmt(s.file_changes)} file changes`}>
              <b>{sub ? 'Sub-agent' : s.agent}</b>
              <span>{s.title || base(s.project) || s.session_id.slice(0, 8)}</span>
            </button>
            <div className="wd-track">
              <div className="wd-span" style={{ left: `${(100 * a) / 86400}%`, width: `${Math.max(0.3, (100 * (b - a)) / 86400)}%` }} />
              {s.marks.map((m) => (
                <button key={m.rowid} className={'wd-mark ' + MARK[m.kind].cls} style={{ left: `${(100 * secOfDay(m.ts)) / 86400}%` }}
                  title={`${m.ts.slice(11, 19)} UTC — ${MARK[m.kind].label}${m.words ? ':\n' + m.words : ''}`}
                  onClick={() => onRows({ db: 'ai_agents', table: 'ai_agent_steps', rowids: [m.rowid], title: `${s.agent}: ${MARK[m.kind].label}` })} />
              ))}
            </div>
            <span className="wd-lane-n">{fmt(s.marks_total)}</span>
          </div>
        )
      })}
      <div className="wd-keys">
        {Object.entries(MARK).map(([k, m]) => <span key={k}><i className={'wd-mark static ' + m.cls} />{m.label}</span>)}
      </div>
      {data.total_sessions > data.shown_sessions && (
        <p className="wd-note">The {fmt(data.shown_sessions)} busiest of {fmt(data.total_sessions)} sessions on this day are drawn.</p>
      )}
    </div>
  )
}

// ---------------------------------------------------------------- input layer
function InputLayer({ day, callAsync, onRows }) {
  const [data, setData] = useState(null)
  const [all, setAll] = useState(false)
  useEffect(() => {
    let live = true
    setData(null)
    callAsync('getInputLayer', JSON.stringify({ day }))
      .then((r) => { if (live) setData(r || { available: false, reason: 'The input record could not be read.' }) })
    return () => { live = false }
  }, [day, callAsync])
  if (!data) return <div className="wd-loading">Reading Windows' keyboard, mouse and focus record…</div>
  if (!data.available || !data.programs.length) return <Empty text={data.reason || 'SRUM recorded no program on this day.'} />
  const progs = all ? data.programs : data.programs.slice(0, 12)
  const seg = (a, b) => ({ left: `${(100 * a) / 86400}%`, width: `${Math.max(0.12, (100 * (b - a)) / 86400)}%` })
  return (
    <div className="wd-lanes input">
      <div className="wd-axis">{[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => <span key={h} style={{ left: `${(100 * h) / 24}%` }}>{String(h).padStart(2, '0')}</span>)}</div>
      {progs.map((p) => (
        <div className="wd-lane" key={p.app}>
          <button className="wd-lane-label" title={`${p.label}\n${p.users.join(', ')}\nOpen its ${p.rowids.length} SRUM rows`}
            onClick={() => onRows({ db: 'srum', table: 'srum_app_timeline', rowids: p.rowids, title: `${p.label} on ${day}` })}>
            <b>{base(p.label)}</b>
            <span>{p.in_front ? 'in front at times' : 'only in the background'}</span>
          </button>
          <div className="wd-track" onClick={() => onRows({ db: 'srum', table: 'srum_app_timeline', rowids: p.rowids, title: `${p.label} on ${day}` })}>
            {p.stretches.map(([a, b, fg], i) => <span key={'s' + i} className={'wd-stretch' + (fg ? ' fg' : '')} style={seg(a, b)} />)}
            {p.focus_runs.map(([a, b], i) => <span key={'f' + i} className="wd-run focus" style={seg(a, b)} title={`In front ${hh(a)}–${hh(b)}`} />)}
            {p.input_runs.map(([a, b], i) => <span key={'i' + i} className="wd-run input" style={seg(a, b)} title={`Input ${hh(a)}–${hh(b)}`} />)}
            {p.keyboard_runs.map(([a, b], i) => <span key={'k' + i} className="wd-run keys" style={seg(a, b)} title={`Keyboard ${hh(a)}–${hh(b)}`} />)}
          </div>
          <span className="wd-lane-nums" title="Over the SRUM stretches that touch this day">
            <b>{dur(p.focus_s)}</b> in front
            <i>keyboard {dur(p.keyboard_s)} · mouse {dur(p.mouse_s)}</i>
          </span>
        </div>
      ))}
      <div className="wd-keys">
        <span><i className="wd-run static focus" />In front (4-second record)</span>
        <span><i className="wd-run static input" />Keyboard or mouse input</span>
        <span><i className="wd-run static keys" />Keyboard input</span>
        <span><i className="wd-stretch static fg" />A stretch with focus</span>
        <span><i className="wd-stretch static" />A stretch only in the background</span>
      </div>
      <p className="wd-note">
        Windows keeps the second-by-second record only for the last minutes of each stretch, so the runs are samples; the
        numbers are the stretch totals. Input sent by software counts as keyboard input here too.
        {data.total_programs > progs.length && (
          <> <button className="wd-link" onClick={() => setAll(!all)}>{all ? 'Show the busiest 12' : `Show all ${fmt(data.programs.length)}${data.total_programs > data.programs.length ? ` of ${fmt(data.total_programs)}` : ''}`}</button></>
        )}
      </p>
    </div>
  )
}

// ---------------------------------------------------------------- per person
function Spark({ weeks }) {
  if (!weeks || weeks.length < 2) return <span className="wd-spark-none">—</span>
  const w = 120
  const h = 26
  const pts = weeks.map((x, i) => `${(i * w) / (weeks.length - 1)},${h - (h * (x.events ? x.automation / x.events : 0))}`)
  return (
    <svg className="wd-spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <title>{weeks.map((x) => `${x.week}: ${pct(x.automation, x.events)}% automation of ${fmt(x.events)}`).join('\n')}</title>
      <polyline points={pts.join(' ')} fill="none" stroke={DRIVER_STYLE.ai_agent.color} strokeWidth="1.6" />
    </svg>
  )
}

function People({ filters, callBridge, onOpen }) {
  const [data, setData] = useState(null)
  const [showComputer, setShowComputer] = useState(false)
  const key = JSON.stringify(filters)
  useEffect(() => {
    let live = true
    callBridge('getDriversByPerson', key).then((r) => { if (live && r && !r.pending) setData(r) })
    return () => { live = false }
  }, [key, callBridge])
  if (!data) return <div className="wd-loading">Counting per person…</div>
  if (!data.people.length) return <Empty text="No activity in this view." />
  const who = (p) => (p.actor_sid ? { actor_sids: [p.actor_sid] } : { actors: [p.person] })
  const computer = data.people.filter((p) => p.kind === 'computer')
  const rows = showComputer ? data.people : data.people.filter((p) => p.kind !== 'computer')
  if (!rows.length && !showComputer) {
    return (
      <>
        <Empty text="No person's activity in this view: only the computer's own and service accounts." />
        <button className="wd-link" onClick={() => setShowComputer(true)}>Show them ({fmt(computer.length)})</button>
      </>
    )
  }
  return (
    <>
    <table className="wd-people">
      <thead><tr><th>Person</th><th>Who drove their activities</th><th>AI agents · folders</th><th>Automation by week</th></tr></thead>
      <tbody>
        {rows.map((p) => (
          <tr key={p.actor_sid + '|' + p.person} className={p.kind === 'computer' ? 'wd-computer' : ''}>
            <td><b>{p.person || 'Not tied to a person'}</b><span className="wd-dim">{fmt(p.events)} activities</span></td>
            <td>
              <div className="wd-share small">
                {DRIVERS.map((k) => (p.by_driver[k] ? (
                  <button key={k} className="wd-share-seg" style={{ flexGrow: p.by_driver[k], background: DRIVER_STYLE[k].color }}
                    title={`${DRIVER_STYLE[k].label}: ${fmt(p.by_driver[k])} (${pct(p.by_driver[k], p.events)}%)`}
                    onClick={() => onOpen({ ...who(p), drivers: [k] })} />
                ) : null))}
              </div>
              <span className="wd-dim">
                {DRIVERS.filter((k) => p.by_driver[k]).map((k) => `${DRIVER_STYLE[k].short} ${pct(p.by_driver[k], p.events)}%`).join(' · ')}
              </span>
            </td>
            <td>
              {p.agents.length ? p.agents.map((a) => <span className="wd-chip" key={a.agent}>{a.agent}</span>) : <span className="wd-dim">none recorded</span>}
              {p.folders.slice(0, 3).map((f) => <span className="wd-chip dim" key={f.folder} title={f.folder}>{base(f.folder)}</span>)}
            </td>
            <td><Spark weeks={p.weeks} /></td>
          </tr>
        ))}
      </tbody>
    </table>
    {computer.length > 0 && (
      <p className="wd-note">
        <button className="wd-link" onClick={() => setShowComputer(!showComputer)}>
          {showComputer ? 'Hide' : 'Show'} the computer's own and service accounts ({fmt(computer.length)}, {fmt(computer.reduce((a, p) => a + p.events, 0))} activities)
        </button>
      </p>
    )}
    </>
  )
}

// ---------------------------------------------------------------- the view
export default function WhoDroveView({ summary, filters, callBridge, callAsync, onOpenStory, onOpenRows, initialDay }) {
  const lastDay = useMemo(() => {
    const days = (summary && summary.driver_heatmap ? summary.driver_heatmap : []).map((c) => c.day).sort()
    return days.length ? days[days.length - 1] : ''
  }, [summary])
  const [day, setDay] = useState(initialDay || '')
  useEffect(() => { if (initialDay) setDay(initialDay) }, [initialDay])
  const shownDay = day || lastDay
  if (!summary) return <div className="wd-loading">Loading…</div>
  return (
    <div className="who-drove">
      <div className="wd-intro">
        <h2>Who drove it</h2>
        <p>
          Each activity says what drove it, from evidence only: a person's keyboard and mouse input, a remote
          sign-in, a program on its own, a script, or an AI agent's own record of what it ran. Every number opens
          the activities or the rows behind it.
        </p>
      </div>
      <Section title="Everything in this view" sub="Click a tile or a part of the bar to read those activities in the Activity Story.">
        <DriverTiles summary={summary} onOpen={onOpenStory} />
      </Section>
      <Section title="Who drove each day" sub="One row per kind of driver, one cell per day; a stronger colour is more activities. Click a day to see its hours, its AI agent sessions and its keyboard and mouse record below.">
        <DayStripByDriver summary={summary} day={shownDay} onDay={setDay} />
      </Section>
      {shownDay && (
        <>
          <Section title={`${shownDay}, hour by hour`} sub="Times are UTC. Click a coloured part to read those activities.">
            <HourBars summary={summary} day={shownDay} onOpen={onOpenStory} />
          </Section>
          <Section title={`AI agent sessions on ${shownDay}`} sub="From the agents' own session records (Claude Code, Gemini CLI, Codex): each request, the commands the agent ran, the files it changed. Click a mark for its full row.">
            <AgentSessions day={shownDay} callAsync={callAsync} onRows={onOpenRows} />
          </Section>
          <Section title={`Keyboard, mouse and focus on ${shownDay}`} sub="Windows' own record per program (SRUM App Timeline): when it was the window in front, and when it received input. Click a program for its rows.">
            <InputLayer day={shownDay} callAsync={callAsync} onRows={onOpenRows} />
          </Section>
        </>
      )}
      <Section title="Per person" sub="How each person's activities were driven, the AI agents and folders they worked with, and the share of automation week by week. Click a part of a bar to read those activities.">
        <People filters={filters} callBridge={callAsync || callBridge} onOpen={onOpenStory} />
      </Section>
    </div>
  )
}
