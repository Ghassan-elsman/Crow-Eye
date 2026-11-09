import React, { useEffect, useMemo, useRef, useState } from 'react'
import { call, latest } from './bridge.js'
import ActivityStrip from './ActivityStrip.jsx'
import OverviewPanel from './OverviewPanel.jsx'
import DaySection from './DaySection.jsx'
import DateDropdown from './DateDropdown.jsx'
import { IconDatabase } from './Icons.jsx'
import InsightPanel from './InsightPanel.jsx'
import SessionDetailPanel from './SessionDetailPanel.jsx'
import ProgramDetailPanel from './ProgramDetailPanel.jsx'
import LoadingOverlay from './LoadingOverlay.jsx'
import HourDetailPanel from './HourDetailPanel.jsx'

const INSIGHT_TITLE = {
  failedCommands: 'Commands that failed',
  credentialFiles: 'Credential stores an agent read or changed',
  bypassSessions: 'Sessions that ran with approvals off',
  goneTranscripts: 'Sessions whose transcript is gone',
  notFromPerson: 'Prompts nobody typed',
  refusedCalls: 'Calls refused before they ran',
}
const INSIGHT_HINT = {
  failedCommands: 'A non-zero exit code from the agent\'s own record (Claude Code background tasks, Codex, Gemini, Copilot). A failed attempt is still an attempt: what was it trying to do?',
  credentialFiles: 'SSH or cloud keys, browser saved logins or cookies, DPAPI master keys, password vaults. An agent reading one may be doing its job (a deploy key) or not; the session shows why.',
  bypassSessions: 'The agent ran commands without asking first (bypassPermissions, danger-full-access, never-ask). Whatever it ran, the person did not approve each step.',
  goneTranscripts: 'The prompts survive (Claude Code history.jsonl, Gemini logs.json) but the session file does not: deleted, or cleaned up by the tool. Read the prompts.',
  notFromPerson: 'What set the agent working with no person typing: a scheduled task, a message from another agent session, a program calling claude -p, or the program resuming on its own (Claude Code records who sent every turn). The person may have set it up; they did not type it.',
  refusedCalls: 'Commands and tool calls stopped before they ran: by the auto-mode classifier, a settings rule or the person. A refused call shows what the agent tried to do.',
}

export default function App() {
  const [bounds, setBounds] = useState(null)
  const [loadErr, setLoadErr] = useState('')
  const [loadMsg, setLoadMsg] = useState('')
  const [terms, setTerms] = useState([])
  const [mode, setMode] = useState('or')
  const [range, setRange] = useState({ start: '', end: '' })
  const [draft, setDraft] = useState('')
  const [agent, setAgent] = useState('')
  const [user, setUser] = useState('')

  const [timeline, setTimeline] = useState(null)
  const [tlLoading, setTlLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [ovLoading, setOvLoading] = useState(true)
  const [selectedDay, setSelectedDay] = useState(null)
  const [dayDetail, setDayDetail] = useState(null)
  const [dayLoading, setDayLoading] = useState(false)

  const [openSession, setOpenSession] = useState(null)
  const [sessionDetail, setSessionDetail] = useState(null)
  const [sessionLoading, setSessionLoading] = useState(false)
  const [openProgram, setOpenProgram] = useState(null)
  const [programDetail, setProgramDetail] = useState(null)
  const [programLoading, setProgramLoading] = useState(false)
  const [openInsight, setOpenInsight] = useState(null)
  const [openHour, setOpenHour] = useState(null)

  const debounce = useRef(null)
  const filterArgs = useMemo(() => ({ terms, mode, ...range, agent, user }), [terms, mode, range, agent, user])

  useEffect(() => {
    call('getAiBounds').then((b) => {
      setBounds(b)
      if (b?.minDate) setRange({ start: b.minDate, end: b.maxDate })
    }).catch((e) => { setBounds({ hasData: false }); setLoadErr(String(e && e.message || e) || 'that query failed') })
  }, [])

  useEffect(() => {
    if (bounds && !bounds.hasData) { setTlLoading(false); setOvLoading(false); return }
    if (!bounds) return
    setTlLoading(true); setOvLoading(true)
    setLoadErr('')
    setLoadMsg('Re-reading the agents\' records for this range…')
    clearTimeout(debounce.current)
    debounce.current = setTimeout(() => {
      latest('getAiTimeline', JSON.stringify(filterArgs)).then(setTimeline).catch((e) => { setTimeline({ sources: {}, combined: [] }); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setTlLoading(false))
      latest('getAiOverview', JSON.stringify(filterArgs)).then(setOverview).catch((e) => { setOverview(null); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setOvLoading(false))
    }, 180)
    return () => clearTimeout(debounce.current)
  }, [filterArgs, bounds])

  useEffect(() => {
    if (!timeline || selectedDay) return
    const last = [...(timeline.combined || [])].reverse().find(d => d.value > 0) || (timeline.combined || [])[(timeline.combined || []).length - 1]
    if (last) setSelectedDay(last.day)
  }, [timeline])

  useEffect(() => {
    if (!selectedDay) { setDayDetail(null); return }
    setDayLoading(true)
    setLoadMsg('Loading the selected day…')
    latest('getAiDayDetail', JSON.stringify({ day: selectedDay, ...filterArgs })).then(setDayDetail).catch((e) => setLoadErr(String(e && e.message || e) || 'that query failed')).finally(() => setDayLoading(false))
  }, [selectedDay, filterArgs])

  useEffect(() => {
    if (!openSession) { setSessionDetail(null); return }
    setSessionLoading(true)
    latest('getAiSessionDetail', JSON.stringify({ session: openSession })).then(setSessionDetail).catch((e) => setLoadErr(String(e && e.message || e) || 'that query failed')).finally(() => setSessionLoading(false))
  }, [openSession])

  useEffect(() => {
    if (!openProgram) { setProgramDetail(null); return }
    setProgramLoading(true)
    latest('getAiProgramDetail', JSON.stringify({ program: openProgram })).then(setProgramDetail).catch((e) => setLoadErr(String(e && e.message || e) || 'that query failed')).finally(() => setProgramLoading(false))
  }, [openProgram])

  function addTerm(e) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      const t = draft.trim().replace(/,$/, '')
      if (t && !terms.includes(t)) setTerms([...terms, t])
      setDraft('')
    } else if (e.key === 'Backspace' && !draft && terms.length) setTerms(terms.slice(0, -1))
  }

  if (bounds && !bounds.hasData) {
    return (
      <div className="app empty-state"><div>
        <div className="empty-icon"><IconDatabase size={54} /></div>
        <h2>No AI agent records in this case</h2>
        <p>Parse AI Agents for the current case (Claude Code, Codex, Gemini CLI, Copilot, Antigravity, Roo/Kilo/Cline), then reopen this chart.</p>
        {loadErr ? <p className="err">{loadErr}</p> : null}
      </div></div>
    )
  }
  if (bounds === null || !timeline) {
    return (
      <div className="app loading-screen">
        <div className="loading-box">
          <div className="loading-brand"><span className="brand-mark">AI AGENTS</span><span className="brand-title">what they ran and changed</span></div>
          <div className="loading-dots" aria-hidden="true"><span /><span /><span /></div>
          <div className="loading-title">Reading the agents' session records…</div>
        </div>
      </div>
    )
  }
  const activeDays = new Set((timeline.combined || []).filter(c => c.value > 0).map(c => c.day))
  const openFromInsight = (id) => { setOpenInsight(null); setOpenSession(id) }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">AI AGENTS</span>
          <span className="brand-title">what they ran and changed</span>
          {bounds?.minDate && <span className="brand-range">{bounds.minDate} &rarr; {bounds.maxDate}</span>}
        </div>
        <div className="filters inline">
          <div className="search">
            {terms.map(t => (
              <span className="chip" key={t}>{t}<button onClick={() => setTerms(terms.filter(x => x !== t))}>&times;</button></span>
            ))}
            <input value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={addTerm}
              placeholder={terms.length ? '' : 'Search command, file, program…'} />
          </div>
          {terms.length > 1 && (
            <div className="mode-toggle">
              <button className={mode === 'or' ? 'on' : ''} onClick={() => setMode('or')}>ANY</button>
              <button className={mode === 'and' ? 'on' : ''} onClick={() => setMode('and')}>ALL</button>
            </div>
          )}
          <select className="vol-select" value={agent} onChange={e => setAgent(e.target.value)}>
            <option value="">All agents</option>
            {(bounds.agents || []).map(a => <option key={a.agent} value={a.agent}>{a.agent} ({a.sessions})</option>)}
          </select>
          {(bounds.users || []).length > 1 && (
            <select className="vol-select" value={user} onChange={e => setUser(e.target.value)}>
              <option value="">All accounts</option>
              {bounds.users.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
          )}
          {bounds?.minDate && (
            <DateDropdown bounds={{ minDate: bounds.minDate, maxDate: bounds.maxDate }} activeDays={activeDays} range={range} onChange={setRange} />
          )}
        </div>
      </header>

      <div className="dash">
        <LoadingOverlay show={tlLoading || ovLoading || dayLoading} error={loadErr}
          brand={['AI AGENTS', 'what they ran and changed']} message={loadMsg} />
        <div className="dash-left">
          <section className="hm-section">
            <ActivityStrip timeline={timeline} selectedDay={selectedDay}
              onSelectDay={(d) => { setOpenSession(null); setSelectedDay(d) }} />
          </section>
          <DaySection day={selectedDay} detail={dayDetail} loading={dayLoading}
            onOpenSession={setOpenSession} onOpenProgram={setOpenProgram} onPickHour={setOpenHour} />
        </div>

        {openSession && (
          <div className="modal-overlay" onClick={() => setOpenSession(null)}>
            <div className="modal-card modal-wide" onClick={(e) => e.stopPropagation()}>
              <SessionDetailPanel detail={sessionDetail} loading={sessionLoading}
                onOpenProgram={(p) => { setOpenSession(null); setOpenProgram(p) }}
                onClose={() => setOpenSession(null)} />
            </div>
          </div>
        )}
        {openProgram && (
          <div className="modal-overlay" onClick={() => setOpenProgram(null)}>
            <div className="modal-card modal-wide" onClick={(e) => e.stopPropagation()}>
              <ProgramDetailPanel detail={programDetail} loading={programLoading}
                onOpenSession={(s) => { setOpenProgram(null); setOpenSession(s) }}
                onClose={() => setOpenProgram(null)} />
            </div>
          </div>
        )}
        {openHour !== null && (
          <div className="modal-overlay" onClick={() => setOpenHour(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <HourDetailPanel hour={openHour} day={selectedDay} detail={dayDetail}
                onOpenSession={(s) => { setOpenHour(null); setOpenSession(s) }}
                onClose={() => setOpenHour(null)} />
            </div>
          </div>
        )}
        {openInsight && overview?.insights?.[openInsight] ? (
          <InsightPanel title={INSIGHT_TITLE[openInsight] || 'Insight'} hint={INSIGHT_HINT[openInsight]}
            data={overview.insights[openInsight]} onOpen={openFromInsight} onClose={() => setOpenInsight(null)} />
        ) : null}

        <aside className="dash-right">
          <OverviewPanel overview={overview} loading={ovLoading} onOpenProgram={setOpenProgram} onOpenInsight={setOpenInsight} />
        </aside>
      </div>
    </div>
  )
}
