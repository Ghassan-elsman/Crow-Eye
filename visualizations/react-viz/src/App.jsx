import React, { useEffect, useMemo, useRef, useState } from 'react'
import { call } from './bridge.js'
import HeatmapStack from './HeatmapStack.jsx'
import OverviewPanel from './OverviewPanel.jsx'
import DayActivitySection from './DayActivitySection.jsx'
import DateDropdown from './DateDropdown.jsx'
import { IconDatabase } from './Icons.jsx'
import InsightPanel from './InsightPanel.jsx'
import AppDetailPanel from './AppDetailPanel.jsx'
import LoadingOverlay from './LoadingOverlay.jsx'


const INSIGHT_TITLE = {
  netSkew: 'Applications that sent far more than they received',
  oneDay: 'Applications seen on one day only',
}
const INSIGHT_HINT = {
  netSkew: 'Most software receives more than it sends. The reverse is the shape of an upload - a backup client, a sync agent, or data leaving the machine. Open an application for its per-hour traffic and the accounts it ran under.',
  oneDay: 'An application SRUM recorded on a single day. Installers and update packages look like this; so does something that ran once, did its work, and was removed.',
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

  const [heatmaps, setHeatmaps] = useState(null)
  const [heatLoading, setHeatLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [overviewLoading, setOverviewLoading] = useState(true)

  const [selectedDay, setSelectedDay] = useState(null)
  const [companion, setCompanion] = useState(null)
  const [dayActivity, setDayActivity] = useState(null)
  const [dayLoading, setDayLoading] = useState(false)

  const [selectedApp, setSelectedApp] = useState(null)
  // The period the app modal should cover. An insight spans the whole filter,
  // a heat-map cell is one day; null means "the selected day".
  const [appRange, setAppRange] = useState(null)
  const [appDetail, setAppDetail] = useState(null)
  const [appDetailLoading, setAppDetailLoading] = useState(false)
  const [openInsight, setOpenInsight] = useState(null)

  const debounce = useRef(null)
  const filterArgs = useMemo(() => ({ terms, mode, ...range }), [terms, mode, range])
  const activeDays = useMemo(
    () => new Set((heatmaps?.combined || []).filter(d => d.value > 0).map(d => d.day)),
    [heatmaps])

  useEffect(() => {
    call('getSrumBounds').then((b) => {
      setBounds(b)
      if (b?.minDate) setRange({ start: b.minDate, end: b.maxDate })
    }).catch((e) => { setBounds({ hasData: false }); setLoadErr(String(e && e.message || e) || 'that query failed') })
  }, [])

  // heatmaps + overview reload on filter change
  useEffect(() => {
    if (bounds && !bounds.hasData) { setHeatLoading(false); setOverviewLoading(false); return }
    setHeatLoading(true); setOverviewLoading(true)
    setLoadErr('')
    setLoadMsg('Re-reading the case for this range…')
    clearTimeout(debounce.current)
    debounce.current = setTimeout(() => {
      call('getSrumHeatmaps', JSON.stringify({ ...filterArgs }))
        .then(setHeatmaps).catch((e) => { setHeatmaps({ providers: {}, combined: [] }); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setHeatLoading(false))
      call('getSrumOverview', JSON.stringify({ ...filterArgs }))
        .then(setOverview).catch((e) => { setOverview(null); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setOverviewLoading(false))
    }, 180)
    return () => clearTimeout(debounce.current)
  }, [filterArgs, bounds])

  // Open on the most recent activity: the last cell that carries anything.
  // The strip scrolls to its recent end, so a selection from years back would
  // leave the panel below describing a period that is not on screen.
  useEffect(() => {
    if (!heatmaps || selectedDay) return
    const latest = [...(heatmaps.combined || [])].reverse().find(d => d.value > 0) || (heatmaps.combined || [])[(heatmaps.combined || []).length - 1]
    if (latest) setSelectedDay(latest.day)
  }, [heatmaps])

  // day detail + day activity when the selected day or filters change
  useEffect(() => {
    if (!selectedDay) { setCompanion(null); setDayActivity(null); return }
    setDayLoading(true)
    setLoadMsg('Loading the selected period…')
    Promise.all([
      call('getSrumDayDetail', JSON.stringify({ day: selectedDay, ...filterArgs })).then(setCompanion),
      call('getSrumDayActivity', JSON.stringify({ day: selectedDay, topN: 40, ...filterArgs })).then(setDayActivity),
    ]).finally(() => setDayLoading(false))
  }, [selectedDay, filterArgs])

  // App modal, scoped to whatever period opened it.
  //
  // `appRange` is null when the app was opened from something that spans the
  // whole filter rather than one cell - an insight tile. Scoping that to the
  // selected day would open an empty modal underneath a tile that had just
  // counted records across months, so the range the tile used wins.
  useEffect(() => {
    if (!selectedApp) { setAppDetail(null); return }
    setAppDetailLoading(true)
    const scope = appRange || { start: selectedDay, end: selectedDay }
    call('getSrumAppDetail', JSON.stringify({ app: selectedApp, ...scope, terms, mode }))
      .then(setAppDetail).finally(() => setAppDetailLoading(false))
  }, [selectedApp, appRange, selectedDay, terms, mode])

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
        <h2>No SRUM data in this case</h2>
        <p>Parse SRUM for the current case, then reopen this chart.</p>
      </div></div>
    )
  }

  // One polished loading screen for the whole initial load — until bounds AND the
  // first heat-maps are in — instead of flashing a half-built dashboard.
  if (bounds === null || !heatmaps) {
    return (
      <div className="app loading-screen">
        <div className="loading-box">
          <div className="loading-brand">
            <span className="brand-mark">SRUM</span>
            <span className="brand-title">activity</span>
          </div>
          <div className="loading-dots" aria-hidden="true"><span /><span /><span /></div>
          <div className="loading-title">Reading SRUM providers…</div>
        </div>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">SRUM</span>
          <span className="brand-title">activity</span>
          {bounds?.minDate && <span className="brand-range">{bounds.minDate} &rarr; {bounds.maxDate}</span>}
        </div>
        <div className="filters inline">
          <div className="search">
            {terms.map(t => (
              <span className="chip" key={t}>{t}<button onClick={() => setTerms(terms.filter(x => x !== t))}>&times;</button></span>
            ))}
            <input value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={addTerm}
              placeholder={terms.length ? '' : 'Search apps, paths, users…'} />
          </div>
          {terms.length > 1 && (
            <div className="mode-toggle">
              <button className={mode === 'or' ? 'on' : ''} onClick={() => setMode('or')}>ANY</button>
              <button className={mode === 'and' ? 'on' : ''} onClick={() => setMode('and')}>ALL</button>
            </div>
          )}
          {bounds?.minDate && (
            <DateDropdown bounds={bounds} activeDays={activeDays} range={range} onChange={setRange} />
          )}
        </div>
      </header>

      <div className="dash">
        <LoadingOverlay show={heatLoading || overviewLoading || dayLoading} error={loadErr}
          brand={['SRUM', 'activity']}
          message={loadMsg} />
        <div className="dash-left">
          <section className="hm-section">
            <HeatmapStack heatmaps={heatmaps} selectedDay={selectedDay}
              onSelect={(d) => { setSelectedApp(null); setAppRange(null); setSelectedDay(d) }} />
          </section>

          <DayActivitySection
            day={selectedDay} activity={dayActivity} companion={companion} loading={dayLoading}
            selectedApp={selectedApp}
            onSelectApp={(a) => { setAppRange(null); setSelectedApp(a) }} />
        </div>

        <aside className="dash-right">
          <OverviewPanel overview={overview} loading={overviewLoading}
            onOpenApp={(a) => { setAppRange(null); setSelectedApp(a) }}
            onOpenInsight={setOpenInsight} />
        </aside>
      </div>

      {/* Both modals live here, not in DayActivitySection: that section returns
          early when no day is selected, so an insight opened with nothing
          selected would set the state and render nothing at all. */}
      {selectedApp && (
        <div className="modal-overlay" onClick={() => setSelectedApp(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <AppDetailPanel app={selectedApp} detail={appDetail} loading={appDetailLoading}
              onClose={() => setSelectedApp(null)} />
          </div>
        </div>
      )}

      {openInsight && overview?.insights?.[openInsight] ? (
        <InsightPanel
          title={INSIGHT_TITLE[openInsight] || 'Insight'}
          hint={INSIGHT_HINT[openInsight]}
          data={overview.insights[openInsight]}
          onOpen={(app) => {
            setOpenInsight(null)
            // An insight counted records across the whole filter, so the modal
            // it opens has to cover that - scoping it to the selected cell
            // would show an empty profile under a tile that just counted rows.
            setAppRange({ start: range.start, end: range.end })
            setSelectedApp(app)
          }}
          onClose={() => setOpenInsight(null)} />
      ) : null}
    </div>
  )
}
