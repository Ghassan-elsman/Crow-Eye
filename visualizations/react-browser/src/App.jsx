import React, { useEffect, useMemo, useRef, useState } from 'react'
import { call, latest } from './bridge.js'
import BrowserTimeline from './BrowserTimeline.jsx'
import OverviewPanel from './OverviewPanel.jsx'
import DaySection from './DaySection.jsx'
import DomainDetailPanel from './DomainDetailPanel.jsx'
import HourDetailPanel from './HourDetailPanel.jsx'
import DateDropdown from './DateDropdown.jsx'
import { IconDatabase } from './Icons.jsx'
import InsightPanel from './InsightPanel.jsx'
import LoadingOverlay from './LoadingOverlay.jsx'


const INSIGHT_TITLE = {
  historyPruned: 'Domains whose history was pruned',
  flaggedDownloads: 'Downloads the browser warned about',
  executableDownloads: 'Programs and scripts downloaded',
}
const INSIGHT_HINT = {
  historyPruned: 'Cookies, favicons, top sites and sessions outlive a cleared history. A domain carried by two or more of them with no surviving history row is what a prune leaves behind. Domains corroborated by a single artifact are excluded: a third-party cookie is set on sites the user never chose to visit.',
  flaggedDownloads: 'The browser itself objected to these files - its own safe-browsing verdict, recorded at download time. A warning that was overridden is the interesting case.',
  executableDownloads: 'Files that can be run, as opposed to documents and media. Where a program came from is the first question about how it got onto the machine; open one for the domain that served it.',
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
  const [browser, setBrowser] = useState('')
  const [profile, setProfile] = useState('')

  const [heatmaps, setHeatmaps] = useState(null)
  const [hmLoading, setHmLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [ovLoading, setOvLoading] = useState(true)

  const [selectedDay, setSelectedDay] = useState(null)
  const [dayDetail, setDayDetail] = useState(null)
  const [dayLoading, setDayLoading] = useState(false)
  const [dayActivity, setDayActivity] = useState(null)

  const [openHour, setOpenHour] = useState(null)
  const [openDomain, setOpenDomain] = useState(null)
  const [openInsight, setOpenInsight] = useState(null)
  const [domainDetail, setDomainDetail] = useState(null)
  const [domainLoading, setDomainLoading] = useState(false)

  const debounce = useRef(null)
  const filterArgs = useMemo(
    () => ({ terms, mode, ...range, browser, profile }),
    [terms, mode, range, browser, profile])

  useEffect(() => {
    call('getBrowserBounds').then((b) => {
      setBounds(b)
      if (b?.minDate) setRange({ start: b.minDate, end: b.maxDate })
    }).catch((e) => { setBounds({ hasData: false }); setLoadErr(String(e && e.message || e) || 'that query failed') })
  }, [])

  useEffect(() => {
    if (bounds && !bounds.hasData) { setHmLoading(false); return }
    if (!bounds) return
    setHmLoading(true)
    setLoadErr('')
    setOvLoading(true)
    setLoadMsg('Re-reading the case for this range…')
    clearTimeout(debounce.current)
    debounce.current = setTimeout(() => {
      latest('getBrowserHeatmaps', JSON.stringify(filterArgs))
        .then(setHeatmaps).catch((e) => { setHeatmaps({ sources: {}, combined: [] }); setLoadErr(String(e && e.message || e) || 'that query failed') })
        .finally(() => setHmLoading(false))
      latest('getBrowserOverview', JSON.stringify(filterArgs))
        .then(setOverview).catch((e) => { setOverview(null); setLoadErr(String(e && e.message || e) || 'that query failed') })
        .finally(() => setOvLoading(false))
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

  useEffect(() => {
    setOpenHour(null)
    if (!selectedDay) { setDayDetail(null); setDayActivity(null); return }
    setDayLoading(true)
    setLoadMsg('Loading the selected period…')
    latest('getBrowserDayDetail', JSON.stringify({ day: selectedDay, ...filterArgs }))
      .then(setDayDetail).catch((e) => { setDayDetail(null); setLoadErr(String(e && e.message || e) || 'that query failed') })
      .finally(() => setDayLoading(false))
    latest('getBrowserDayActivity', JSON.stringify({ day: selectedDay, topN: 30, ...filterArgs }))
      .then(setDayActivity).catch((e) => { setDayActivity(null); setLoadErr(String(e && e.message || e) || 'that query failed') })
  }, [selectedDay, filterArgs])

  useEffect(() => {
    if (!openDomain) { setDomainDetail(null); return }
    setDomainLoading(true)
    latest('getBrowserDomainDetail', JSON.stringify({ domain: openDomain }))
      .then(setDomainDetail).catch((e) => { setDomainDetail(null); setLoadErr(String(e && e.message || e) || 'that query failed') })
      .finally(() => setDomainLoading(false))
  }, [openDomain])

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
        <h2>No browser data in this case</h2>
        <p>Run Browsers for the current case (Chrome, Edge, Brave, Firefox, Electron apps), then reopen this chart.</p>
      </div></div>
    )
  }

  if (bounds === null || !heatmaps) {
    return (
      <div className="app loading-screen">
        <div className="loading-box">
          <div className="loading-brand"><span className="brand-mark">BROWSERS</span><span className="brand-title">activity</span></div>
          <div className="loading-dots" aria-hidden="true"><span /><span /><span /></div>
          <div className="loading-title">Reading browsing history, downloads, cookies and cache…</div>
        </div>
      </div>
    )
  }

  const activeDays = new Set((heatmaps.combined || []).map(c => c.day))

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">BROWSERS</span>
          <span className="brand-title">activity</span>
          {bounds?.minDate && <span className="brand-range">{bounds.minDate} &rarr; {bounds.maxDate}</span>}
        </div>
        <div className="filters inline">
          <div className="search">
            {terms.map(t => (
              <span className="chip" key={t}>{t}<button onClick={() => setTerms(terms.filter(x => x !== t))}>&times;</button></span>
            ))}
            <input value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={addTerm}
              placeholder={terms.length ? '' : 'Search domain, URL, title, file…'} />
          </div>
          {terms.length > 1 && (
            <div className="mode-toggle">
              <button className={mode === 'or' ? 'on' : ''} onClick={() => setMode('or')}>ANY</button>
              <button className={mode === 'and' ? 'on' : ''} onClick={() => setMode('and')}>ALL</button>
            </div>
          )}
          {(bounds.browsers || []).length > 1 && (
            <select className="vol-select" value={browser} onChange={e => setBrowser(e.target.value)}>
              <option value="">All browsers</option>
              {bounds.browsers.map(b => <option key={b} value={b}>{b}</option>)}
            </select>
          )}
          {(bounds.profiles || []).length > 1 && (
            <select className="vol-select" value={profile} onChange={e => setProfile(e.target.value)}>
              <option value="">All profiles</option>
              {bounds.profiles.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
          )}
          {bounds?.minDate && (
            <DateDropdown bounds={{ minDate: bounds.minDate, maxDate: bounds.maxDate }}
              activeDays={activeDays} range={range} onChange={setRange} />
          )}
        </div>
      </header>

      <div className="dash">
        <LoadingOverlay show={hmLoading || ovLoading || dayLoading} error={loadErr}
          brand={['BROWSERS', 'activity']}
          message={loadMsg} />
        <div className="dash-left">
          <section className="hm-section">
            <BrowserTimeline heatmaps={heatmaps} selectedDay={selectedDay}
              onSelect={(d) => { setOpenDomain(null); setSelectedDay(d) }} />
          </section>

          <DaySection day={selectedDay} detail={dayDetail} activity={dayActivity}
            onPickDomain={setOpenDomain} onPickHour={setOpenHour} />
        </div>

        <aside className="dash-right">
          <OverviewPanel overview={overview} onPickDomain={setOpenDomain}
            onOpenInsight={setOpenInsight} />
        </aside>
      </div>

      {/* This panel used to be mounted bare - the only modal in the fleet with
          no overlay, so it did not dim the page behind it and clicking away
          did nothing. */}
      {openHour !== null && !openDomain && (
        <div className="modal-overlay" onClick={() => setOpenHour(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <HourDetailPanel hour={openHour} day={selectedDay} detail={dayDetail}
              activity={dayActivity}
              onPickDomain={(dn) => { setOpenHour(null); setOpenDomain(dn) }}
              onClose={() => setOpenHour(null)} />
          </div>
        </div>
      )}

      {openDomain && (
        <DomainDetailPanel detail={domainDetail} loading={domainLoading} onClose={() => setOpenDomain(null)} />
      )}

      {/* In `App`, like the domain modal: a panel inside a section that returns
          early when nothing is selected can be opened and render nothing. */}
      {openInsight && overview?.insights?.[openInsight] ? (
        <InsightPanel
          title={INSIGHT_TITLE[openInsight] || 'Insight'}
          hint={INSIGHT_HINT[openInsight]}
          data={overview.insights[openInsight]}
          onOpen={(domain) => { setOpenInsight(null); setOpenDomain(domain) }}
          onClose={() => setOpenInsight(null)} />
      ) : null}
    </div>
  )
}
