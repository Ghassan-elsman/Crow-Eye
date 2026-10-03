import React, { useEffect, useMemo, useRef, useState } from 'react'
import { call } from './bridge.js'
import LocationTimeline from './LocationTimeline.jsx'
import OverviewPanel from './OverviewPanel.jsx'
import DaySection from './DaySection.jsx'
import DateDropdown from './DateDropdown.jsx'
import { LOCATIONS } from './format.js'
import { IconDatabase } from './Icons.jsx'
import InsightPanel from './InsightPanel.jsx'
import ProgramDetailPanel from './ProgramDetailPanel.jsx'
import LoadingOverlay from './LoadingOverlay.jsx'
import HourDetailPanel from './HourDetailPanel.jsx'


const INSIGHT_TITLE = {
  userTemp: 'Programs run from User / AppData / Temp',
  removable: 'Programs run from a removable or other volume',
  singleRun: 'Programs that ran only once',
}
const INSIGHT_HINT = {
  userTemp: 'Software that executes from a user-writable directory rather than Program Files is worth accounting for - installers and updaters do it legitimately, so does malware.',
  removable: 'Execution from a volume that is not the system disk. Check the volume against the device history.',
  singleRun: 'A program that ran once and never again. Common for installers; also the shape of something that ran, did its job, and was removed.',
}

export default function App() {
  const [bounds, setBounds] = useState(null)
  // A failed bridge call used to be swallowed by a .catch() that
  // substituted empty data, so "the query failed" and "this case has
  // no data" looked identical on screen.
  const [loadErr, setLoadErr] = useState('')
  const [loadMsg, setLoadMsg] = useState('')
  const [terms, setTerms] = useState([])
  const [mode, setMode] = useState('or')
  const [range, setRange] = useState({ start: '', end: '' })
  const [draft, setDraft] = useState('')
  const [location, setLocation] = useState('')
  const [volume, setVolume] = useState('')

  const [timeline, setTimeline] = useState(null)
  const [tlLoading, setTlLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [ovLoading, setOvLoading] = useState(true)

  const [selectedDay, setSelectedDay] = useState(null)
  const [dayDetail, setDayDetail] = useState(null)
  const [dayLoading, setDayLoading] = useState(false)

  const [openProgram, setOpenProgram] = useState(null)
  const [openInsight, setOpenInsight] = useState(null)
  const [openHour, setOpenHour] = useState(null)
  const [programDetail, setProgramDetail] = useState(null)
  const [programLoading, setProgramLoading] = useState(false)

  const debounce = useRef(null)
  const filterArgs = useMemo(() => ({ terms, mode, ...range, location, volume }), [terms, mode, range, location, volume])

  useEffect(() => {
    call('getPrefetchBounds').then((b) => {
      setBounds(b)
      if (b?.minDate) setRange({ start: b.minDate, end: b.maxDate })
    }).catch((e) => { setBounds({ hasData: false }); setLoadErr(String(e && e.message || e) || 'that query failed') })
  }, [])

  useEffect(() => {
    if (bounds && !bounds.hasData) { setTlLoading(false); setOvLoading(false); return }
    if (!bounds) return
    setTlLoading(true); setOvLoading(true)
    setLoadErr('')
    setLoadMsg('Re-reading the case for this range…')
    clearTimeout(debounce.current)
    debounce.current = setTimeout(() => {
      call('getPrefetchTimeline', JSON.stringify(filterArgs)).then(setTimeline).catch((e) => { setTimeline({ sources: {}, combined: [] }); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setTlLoading(false))
      call('getPrefetchOverview', JSON.stringify(filterArgs)).then(setOverview).catch((e) => { setOverview(null); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setOvLoading(false))
    }, 180)
    return () => clearTimeout(debounce.current)
  }, [filterArgs, bounds])

  useEffect(() => {
    if (!timeline || selectedDay) return
  // Open on the most recent activity: the last cell that carries anything.
  // The strip scrolls to its recent end, so a selection from years back would
  // leave the panel below describing a period that is not on screen.
    const latest = [...(timeline.combined || [])].reverse().find(d => d.value > 0) || (timeline.combined || [])[(timeline.combined || []).length - 1]
    if (latest) setSelectedDay(latest.day)
  }, [timeline])

  useEffect(() => {
    if (!selectedDay) { setDayDetail(null); return }
    setDayLoading(true)
    setLoadMsg('Loading the selected period…')
    call('getPrefetchDayDetail', JSON.stringify({ day: selectedDay, ...filterArgs })).then(setDayDetail).finally(() => setDayLoading(false))
  }, [selectedDay, filterArgs])

  useEffect(() => {
    if (!openProgram) { setProgramDetail(null); return }
    setProgramLoading(true)
    call('getPrefetchProgramDetail', JSON.stringify({ filename: openProgram })).then(setProgramDetail).finally(() => setProgramLoading(false))
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
        <h2>No Prefetch data in this case</h2>
        <p>Parse Prefetch for the current case, then reopen this chart.</p>
      </div></div>
    )
  }

  if (bounds === null || !timeline) {
    return (
      <div className="app loading-screen">
        <div className="loading-box">
          <div className="loading-brand"><span className="brand-mark">PREFETCH</span><span className="brand-title">executions</span></div>
          <div className="loading-dots" aria-hidden="true"><span /><span /><span /></div>
          <div className="loading-title">Reading program-execution history…</div>
        </div>
      </div>
    )
  }

  const activeDays = new Set((timeline.combined || []).map(c => c.day))

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">PREFETCH</span>
          <span className="brand-title">executions</span>
          {bounds?.minDate && <span className="brand-range">{bounds.minDate} &rarr; {bounds.maxDate}</span>}
        </div>
        <div className="filters inline">
          <div className="search">
            {terms.map(t => (
              <span className="chip" key={t}>{t}<button onClick={() => setTerms(terms.filter(x => x !== t))}>&times;</button></span>
            ))}
            <input value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={addTerm}
              placeholder={terms.length ? '' : 'Search program, path, volume…'} />
          </div>
          {terms.length > 1 && (
            <div className="mode-toggle">
              <button className={mode === 'or' ? 'on' : ''} onClick={() => setMode('or')}>ANY</button>
              <button className={mode === 'and' ? 'on' : ''} onClick={() => setMode('and')}>ALL</button>
            </div>
          )}
          <select className="vol-select" value={location} onChange={e => setLocation(e.target.value)}>
            <option value="">All locations</option>
            {LOCATIONS.map(l => <option key={l.key} value={l.key}>{l.label}</option>)}
          </select>
          {(bounds.volumes || []).length > 1 && (
            <select className="vol-select" value={volume} onChange={e => setVolume(e.target.value)}>
              <option value="">All volumes</option>
              {bounds.volumes.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          )}
          {bounds?.minDate && (
            <DateDropdown bounds={{ minDate: bounds.minDate, maxDate: bounds.maxDate }} activeDays={activeDays} range={range} onChange={setRange} />
          )}
        </div>
      </header>

      <div className="dash">
        <LoadingOverlay show={tlLoading || ovLoading || dayLoading} error={loadErr}
          brand={['PREFETCH', 'executions']}
          message={loadMsg} />
        <div className="dash-left">
          <section className="hm-section">
            <LocationTimeline timeline={timeline} selectedDay={selectedDay}
              onSelectDay={(d) => { setOpenProgram(null); setSelectedDay(d) }} />
          </section>

          <DaySection day={selectedDay} detail={dayDetail} loading={dayLoading}
            onOpenProgram={setOpenProgram} onPickHour={setOpenHour} />
        </div>

        {/* The detail modal used to live inside DaySection, which returns
            early when no day is selected - so opening a record from an
            insight closed the insight panel and showed nothing at all. It
            is not part of a day, so it renders here. */}
        {openProgram && (
          <div className="modal-overlay" onClick={() => setOpenProgram(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <ProgramDetailPanel detail={programDetail} loading={programLoading} onClose={() => setOpenProgram(null)} />
            </div>
          </div>
        )}

        {openHour !== null && (
          <div className="modal-overlay" onClick={() => setOpenHour(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <HourDetailPanel hour={openHour} day={selectedDay} detail={dayDetail}
                onOpenProgram={(fn) => { setOpenHour(null); setOpenProgram(fn) }}
                onClose={() => setOpenHour(null)} />
            </div>
          </div>
        )}

        {openInsight && overview?.insights?.[openInsight] ? (
          <InsightPanel
            title={INSIGHT_TITLE[openInsight] || 'Insight'}
            hint={INSIGHT_HINT[openInsight]}
            data={overview.insights[openInsight]}
            onOpen={(id) => { setOpenInsight(null); setOpenProgram(id) }}
            onClose={() => setOpenInsight(null)} />
        ) : null}

        <aside className="dash-right">
          <OverviewPanel overview={overview} loading={ovLoading} onOpenProgram={setOpenProgram}
            onOpenInsight={setOpenInsight} />
        </aside>
      </div>
    </div>
  )
}
