import React, { useEffect, useMemo, useRef, useState } from 'react'
import { call, latest } from './bridge.js'
import TimelineStack from './TimelineStack.jsx'
import OverviewPanel from './OverviewPanel.jsx'
import WindowSection from './WindowSection.jsx'
import DateDropdown from './DateDropdown.jsx'
import { IconDatabase } from './Icons.jsx'
import FileDetailPanel from './FileDetailPanel.jsx'
import InsightPanel from './InsightPanel.jsx'
import LoadingOverlay from './LoadingOverlay.jsx'
import HourDetailPanel from './HourDetailPanel.jsx'
import AllRecordsSection from './AllRecordsSection.jsx'


const INSIGHT_TITLE = {
  timestompCandidates: 'Timestomp candidates',
  usnGaps: 'Gaps in the USN journal',
  deletedButPresent: 'Deleted, still present in the MFT',
  ads: 'Files carrying an alternate data stream',
  renames: 'Renames - old name to new name',
}
const INSIGHT_HINT = {
  timestompCandidates: 'Standard-Info creation is newer than the kernel-written File-Name creation (forward-dating: File-Name is not user-settable). A candidate, not a verdict - open a file and read its two time sets.',
  usnGaps: 'Ranges of USN records that are missing from the journal. These are gaps, not files, so there is nothing to open - but a gap is where evidence would have been.',
  deletedButPresent: 'The MFT record still exists and is marked deleted, so the file name and its times survive even though the data may not.',
  ads: 'A named stream attached to a file. Ordinary for downloads (Zone.Identifier); also a classic place to park a payload.',
  renames: 'Each rename the USN journal recorded, newest first: the RENAME_OLD_NAME record paired with the RENAME_NEW_NAME that follows it for the same file. A move to another folder says so. The MFT keeps current names only, so this is the only name history there is.',
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
  // No range until the analyst picks one: the strip covers the MFT history
  // and the journal together, and opens on the latest six months. It used to
  // start pinned to the journal's own dates, which on a busy machine is one
  // day - the MFT history never appeared.
  const [range, setRange] = useState({ start: '', end: '' })
  const [draft, setDraft] = useState('')
  const [volume, setVolume] = useState('')

  const [timelines, setTimelines] = useState(null)
  const [tlLoading, setTlLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [ovLoading, setOvLoading] = useState(true)

  const [selectedBucket, setSelectedBucket] = useState(null)
  const [windowDetail, setWindowDetail] = useState(null)
  const [winLoading, setWinLoading] = useState(false)
  const [eventsPage, setEventsPage] = useState(null)
  const [evLoading, setEvLoading] = useState(false)

  const [openRec, setOpenRec] = useState(null)
  const [openInsight, setOpenInsight] = useState(null)
  const [openHour, setOpenHour] = useState(null)
  const [hourPage, setHourPage] = useState(null)
  const [hourLoading, setHourLoading] = useState(false)
  const [fileDetail, setFileDetail] = useState(null)
  const [fileLoading, setFileLoading] = useState(false)

  const debounce = useRef(null)
  const filterArgs = useMemo(() => ({ terms, mode, ...range, volume }), [terms, mode, range, volume])

  useEffect(() => {
    call('getMftUsnBounds').then(setBounds)
      .catch((e) => { setBounds({ hasData: false }); setLoadErr(String(e && e.message || e) || 'that query failed') })
  }, [])

  useEffect(() => {
    if (bounds && !bounds.hasData) { setTlLoading(false); setOvLoading(false); return }
    if (!bounds) return
    setTlLoading(true); setOvLoading(true)
    setLoadErr('')
    setLoadMsg('Re-reading the case for this range…')
    clearTimeout(debounce.current)
    debounce.current = setTimeout(() => {
      latest('getMftUsnTimelines', JSON.stringify(filterArgs)).then(setTimelines).catch((e) => { setTimelines({ rows: [], series: {}, combined: [] }); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setTlLoading(false))
      latest('getMftUsnOverview', JSON.stringify(filterArgs)).then(setOverview).catch((e) => { setOverview(null); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setOvLoading(false))
    }, 180)
    return () => clearTimeout(debounce.current)
  }, [filterArgs, bounds])

  // Open on the most recent activity: the last cell that carries anything.
  useEffect(() => {
    if (!timelines || selectedBucket) return
    const latest = [...(timelines.combined || [])].reverse().find(d => d.value > 0) || (timelines.combined || [])[(timelines.combined || []).length - 1]
    if (latest) setSelectedBucket(latest.key)
  }, [timelines])

  useEffect(() => {
    if (!selectedBucket) { setWindowDetail(null); setEventsPage(null); return }
    setWinLoading(true)
    setEventsPage(null)
    setLoadMsg('Loading the selected day…')
    latest('getMftUsnWindowDetail', JSON.stringify({ bucket: selectedBucket, ...filterArgs }))
      .then(setWindowDetail)
      .catch((e) => { setWindowDetail(null); setLoadErr(String(e && e.message || e) || 'that query failed') })
      .finally(() => setWinLoading(false))
  }, [selectedBucket, filterArgs])

  function goPage(page) {
    setEvLoading(true)
    latest('getMftUsnDayEvents', JSON.stringify({ bucket: selectedBucket, page, ...filterArgs }), 'dayEvents')
      .then(setEventsPage)
      .catch((e) => setLoadErr(String(e && e.message || e) || 'that query failed'))
      .finally(() => setEvLoading(false))
  }

  // An hour bar opens that hour - its own records, paged (see HourDetailPanel).
  function loadHour(hour, page) {
    setHourLoading(true)
    latest('getMftUsnDayEvents', JSON.stringify({ bucket: selectedBucket, hour, page, ...filterArgs }), 'hourEvents')
      .then(setHourPage)
      .catch((e) => setLoadErr(String(e && e.message || e) || 'that query failed'))
      .finally(() => setHourLoading(false))
  }
  useEffect(() => {
    if (openHour === null) { setHourPage(null); return }
    loadHour(openHour, 0)
  }, [openHour])

  useEffect(() => {
    if (openRec == null) { setFileDetail(null); return }
    setFileLoading(true)
    latest('getMftUsnFileDetail', JSON.stringify({ id: openRec })).then(setFileDetail).finally(() => setFileLoading(false))
  }, [openRec])

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
        <h2>No MFT/USN correlated data in this case</h2>
        <p>Parse MFT + USN (and run the correlator), then reopen this chart.</p>
      </div></div>
    )
  }

  if (bounds === null || !timelines) {
    return (
      <div className="app loading-screen">
        <div className="loading-box">
          <div className="loading-brand"><span className="brand-mark">MFT&middot;USN</span><span className="brand-title">activity</span></div>
          <div className="loading-dots" aria-hidden="true"><span /><span /><span /></div>
          <div className="loading-title">Correlating MFT records with USN events…</div>
        </div>
      </div>
    )
  }

  const activeDays = new Set((timelines.combined || []).filter(c => c.value > 0).map(c => String(c.key).slice(0, 10)))

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">MFT&middot;USN</span>
          <span className="brand-title">activity</span>
          {bounds?.usnMin && <span className="brand-range" title="The USN journal's own span; the MFT history runs further back">journal {bounds.usnMin}{bounds.usnMax !== bounds.usnMin ? ` → ${bounds.usnMax}` : ''}</span>}
        </div>
        <div className="filters inline">
          <div className="search">
            {terms.map(t => (
              <span className="chip" key={t}>{t}<button onClick={() => setTerms(terms.filter(x => x !== t))}>&times;</button></span>
            ))}
            <input value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={addTerm}
              placeholder={terms.length ? '' : 'Search path, filename, type…'} />
          </div>
          {terms.length > 1 && (
            <div className="mode-toggle">
              <button className={mode === 'or' ? 'on' : ''} onClick={() => setMode('or')}>ANY</button>
              <button className={mode === 'and' ? 'on' : ''} onClick={() => setMode('and')}>ALL</button>
            </div>
          )}
          {bounds?.hasVolume && (bounds.volumes || []).length > 1 && (
            <select className="vol-select" value={volume} onChange={e => setVolume(e.target.value)}>
              <option value="">All volumes</option>
              {bounds.volumes.map(v => <option key={v} value={v}>{v}</option>)}
            </select>
          )}
          {bounds?.min && (
            <DateDropdown bounds={{ minDate: bounds.min, maxDate: bounds.max }} activeDays={activeDays} range={range} onChange={setRange} />
          )}
        </div>
      </header>

      <div className="dash">
        <LoadingOverlay show={tlLoading || ovLoading || winLoading} error={loadErr}
          brand={['MFT&middot;USN', 'activity']}
          message={loadMsg} />
        <div className="dash-left">
          <section className="hm-section">
            <TimelineStack timelines={timelines} selectedBucket={selectedBucket}
              onSelectBucket={(k) => { setOpenRec(null); setSelectedBucket(k) }} />
          </section>

          <WindowSection bucket={selectedBucket} detail={windowDetail} events={eventsPage}
            loading={winLoading} eventsLoading={evLoading}
            onOpenFile={setOpenRec} onPickHour={setOpenHour} onPage={goPage} filterArgs={filterArgs} />

          <AllRecordsSection filterArgs={filterArgs} onOpenFile={setOpenRec} />
        </div>

        {/* The file modal used to live inside WindowSection, which returns
            early when no bucket is selected - so opening a record from an
            anomaly showed nothing at all. It is not part of a window. */}
        {openRec != null && (
          <div className="modal-overlay" onClick={() => setOpenRec(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <FileDetailPanel detail={fileDetail} loading={fileLoading}
                onClose={() => setOpenRec(null)} />
            </div>
          </div>
        )}

        {openHour !== null && (
          <div className="modal-overlay" onClick={() => setOpenHour(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <HourDetailPanel hour={openHour} bucket={selectedBucket} detail={windowDetail}
                page={hourPage} loading={hourLoading} onPage={(p) => loadHour(openHour, p)}
                onOpenFile={(id) => { setOpenHour(null); setOpenRec(id) }}
                onClose={() => setOpenHour(null)} />
            </div>
          </div>
        )}

        {openInsight && overview?.anomalies?.[openInsight] ? (
          <InsightPanel
            title={INSIGHT_TITLE[openInsight] || 'Anomaly'}
            hint={INSIGHT_HINT[openInsight]}
            data={overview.anomalies[openInsight]}
            onOpen={(rec) => { setOpenInsight(null); setOpenRec(rec) }}
            onClose={() => setOpenInsight(null)} />
        ) : null}

        <aside className="dash-right">
          <OverviewPanel overview={overview} loading={ovLoading}
            onOpenInsight={setOpenInsight} />
        </aside>
      </div>
    </div>
  )
}
