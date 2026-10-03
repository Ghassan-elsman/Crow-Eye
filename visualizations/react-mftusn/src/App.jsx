import React, { useEffect, useMemo, useRef, useState } from 'react'
import { call } from './bridge.js'
import TimelineStack from './TimelineStack.jsx'
import OverviewPanel from './OverviewPanel.jsx'
import WindowSection from './WindowSection.jsx'
import DateDropdown from './DateDropdown.jsx'
import { IconDatabase } from './Icons.jsx'
import FileDetailPanel from './FileDetailPanel.jsx'
import InsightPanel from './InsightPanel.jsx'
import LoadingOverlay from './LoadingOverlay.jsx'
import HourDetailPanel from './HourDetailPanel.jsx'


const INSIGHT_TITLE = {
  timestompCandidates: 'Timestomp candidates',
  usnGaps: 'Gaps in the USN journal',
  deletedButPresent: 'Deleted, still present in the MFT',
  ads: 'Files carrying an alternate data stream',
}
const INSIGHT_HINT = {
  timestompCandidates: 'Either Standard-Info creation is newer than the kernel-written File-Name creation, or all four SI times are whole seconds while FN keeps sub-second precision. Both are candidates, not verdicts - open a file and read its two time sets.',
  usnGaps: 'Ranges of USN records that are missing from the journal. These are gaps, not files, so there is nothing to open - but a gap is where evidence would have been.',
  deletedButPresent: 'The MFT record still exists and is marked deleted, so the file name and its times survive even though the data may not.',
  ads: 'A named stream attached to a file. Ordinary for downloads (Zone.Identifier); also a classic place to park a payload.',
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
  const [volume, setVolume] = useState('')

  const [timelines, setTimelines] = useState(null)
  const [tlLoading, setTlLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [ovLoading, setOvLoading] = useState(true)

  const [selectedBucket, setSelectedBucket] = useState(null)
  const [windowDetail, setWindowDetail] = useState(null)
  const [winLoading, setWinLoading] = useState(false)

  const [openRec, setOpenRec] = useState(null)
  const [openInsight, setOpenInsight] = useState(null)
  const [openHour, setOpenHour] = useState(null)
  const [fileDetail, setFileDetail] = useState(null)
  const [fileLoading, setFileLoading] = useState(false)

  const debounce = useRef(null)
  const filterArgs = useMemo(() => ({ terms, mode, ...range, volume }), [terms, mode, range, volume])

  useEffect(() => {
    call('getMftUsnBounds').then((b) => {
      setBounds(b)
      if (b?.usnMin) setRange({ start: b.usnMin, end: b.usnMax })
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
      call('getMftUsnTimelines', JSON.stringify(filterArgs)).then(setTimelines).catch((e) => { setTimelines({ mftHistory: [], usnEvents: {}, combined: [] }); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setTlLoading(false))
      call('getMftUsnOverview', JSON.stringify(filterArgs)).then(setOverview).catch((e) => { setOverview(null); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setOvLoading(false))
    }, 180)
    return () => clearTimeout(debounce.current)
  }, [filterArgs, bounds])

  // Open on the most recent activity: the last cell that carries anything.
  // The strip scrolls to its recent end, so a selection from years back would
  // leave the panel below describing a period that is not on screen.
  useEffect(() => {
    if (!timelines || selectedBucket) return
    const latest = [...(timelines.combined || [])].reverse().find(d => d.value > 0) || (timelines.combined || [])[(timelines.combined || []).length - 1]
    if (latest) setSelectedBucket(latest.key)
  }, [timelines])

  useEffect(() => {
    if (!selectedBucket) { setWindowDetail(null); return }
    setWinLoading(true)
    setLoadMsg('Loading the selected period…')
    call('getMftUsnWindowDetail', JSON.stringify({ bucket: selectedBucket, ...filterArgs }))
      .then(setWindowDetail).finally(() => setWinLoading(false))
  }, [selectedBucket, filterArgs])

  useEffect(() => {
    if (openRec == null) { setFileDetail(null); return }
    setFileLoading(true)
    call('getMftUsnFileDetail', JSON.stringify({ rec: openRec })).then(setFileDetail).finally(() => setFileLoading(false))
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

  const activeDays = new Set((timelines.combined || []).map(c => String(c.key).slice(0, 10)))

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">MFT&middot;USN</span>
          <span className="brand-title">activity</span>
          {bounds?.usnMin && <span className="brand-range">USN {bounds.usnMin}{bounds.usnMax !== bounds.usnMin ? ` → ${bounds.usnMax}` : ''}</span>}
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
          {bounds?.usnMin && (
            <DateDropdown bounds={{ minDate: bounds.usnMin, maxDate: bounds.usnMax }} activeDays={activeDays} range={range} onChange={setRange} />
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

          <WindowSection bucket={selectedBucket} detail={windowDetail} loading={winLoading}
            onOpenFile={setOpenRec} onPickHour={setOpenHour} />
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
                onOpenFile={(rec) => { setOpenHour(null); setOpenRec(rec) }}
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
