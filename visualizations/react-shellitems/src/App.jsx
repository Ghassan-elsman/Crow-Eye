import React, { useEffect, useMemo, useRef, useState } from 'react'
import { call } from './bridge.js'
import SourceTimeline from './SourceTimeline.jsx'
import OverviewPanel from './OverviewPanel.jsx'
import DaySection from './DaySection.jsx'
import DateDropdown from './DateDropdown.jsx'
import { SOURCES, LOCATIONS } from './format.js'
import { IconDatabase } from './Icons.jsx'
import InsightPanel from './InsightPanel.jsx'
import ItemDetailPanel from './ItemDetailPanel.jsx'
import LoadingOverlay from './LoadingOverlay.jsx'
import HourDetailPanel from './HourDetailPanel.jsx'
import AllItemsSection from './AllItemsSection.jsx'


const INSIGHT_TITLE = {
  network: 'Places browsed on a network share',
  removable: 'Places browsed on removable or other volumes',
  macMismatch: 'Shellbags whose FAT time disagrees with the registry write',
}
const INSIGHT_HINT = {
  network: 'Folders the user navigated to over the network. Shell items record where someone looked, not only what they opened.',
  removable: 'Navigation on a volume that was not the system disk - corroborate with the device history below.',
  macMismatch: 'The folder time stored inside the shellbag does not match when the registry key was written. Worth reading carefully: it can be ordinary (a copied folder keeps its own times) or it can be tampering.',
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
  const [source, setSource] = useState('')
  const [location, setLocation] = useState('')
  const [volume, setVolume] = useState('')

  const [timeline, setTimeline] = useState(null)
  const [tlLoading, setTlLoading] = useState(true)
  const [overview, setOverview] = useState(null)
  const [ovLoading, setOvLoading] = useState(true)

  const [selectedDay, setSelectedDay] = useState(null)
  const [dayDetail, setDayDetail] = useState(null)
  const [dayLoading, setDayLoading] = useState(false)
  const [dayActivity, setDayActivity] = useState(null)

  const [openItem, setOpenItem] = useState(null)
  const [openInsight, setOpenInsight] = useState(null)
  const [openHour, setOpenHour] = useState(null)
  const [itemDetail, setItemDetail] = useState(null)
  const [itemLoading, setItemLoading] = useState(false)

  const debounce = useRef(null)
  const filterArgs = useMemo(() => ({ terms, mode, ...range, source, location, volume }), [terms, mode, range, source, location, volume])

  // Opened from a table's Charts button: start on that table's source.
  useEffect(() => {
    // Not a data query: if it fails the dashboard simply opens unfiltered,
    // so it is logged rather than raised as a load error over the data.
    (async () => {
      try {
        const f = await call('getShellItemsFocus')
        if (f?.source) setSource(f.source)
      } catch (e) { console.warn('[shellitems] focus source unavailable', e) }
    })()
  }, [])

  useEffect(() => {
    call('getShellItemsBounds').then((b) => {
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
      call('getShellItemsTimeline', JSON.stringify(filterArgs)).then(setTimeline).catch((e) => { setTimeline({ sources: {}, combined: [] }); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setTlLoading(false))
      call('getShellItemsOverview', JSON.stringify(filterArgs)).then(setOverview).catch((e) => { setOverview(null); setLoadErr(String(e && e.message || e) || 'that query failed') }).finally(() => setOvLoading(false))
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
    if (!selectedDay) { setDayDetail(null); setDayActivity(null); return }
    setDayLoading(true)
    setLoadMsg('Loading the selected period…')
    call('getShellItemsDayDetail', JSON.stringify({ day: selectedDay, ...filterArgs })).then(setDayDetail).finally(() => setDayLoading(false))
    call('getShellItemsDayActivity', JSON.stringify({ day: selectedDay, ...filterArgs })).then(setDayActivity).catch((e) => { setDayActivity(null); setLoadErr(String(e && e.message || e) || 'that query failed') })
  }, [selectedDay, filterArgs])

  useEffect(() => {
    if (openItem === null || openItem === undefined) { setItemDetail(null); return }
    setItemLoading(true)
    call('getShellItemsItemDetail', JSON.stringify({ id: openItem })).then(setItemDetail).finally(() => setItemLoading(false))
  }, [openItem])

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
        <h2>No shell-item data in this case</h2>
        <p>Parse the Registry for the current case (Shellbags, RecentDocs, the ComDlg32 MRUs…), then reopen this chart.</p>
      </div></div>
    )
  }

  if (bounds === null || !timeline) {
    return (
      <div className="app loading-screen">
        <div className="loading-box">
          <div className="loading-brand"><span className="brand-mark">SHELL ITEMS</span><span className="brand-title">navigation</span></div>
          <div className="loading-dots" aria-hidden="true"><span /><span /><span /></div>
          <div className="loading-title">Reading user-navigation & MRU history…</div>
        </div>
      </div>
    )
  }

  const activeDays = new Set((timeline.combined || []).map(c => c.day))

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">SHELL ITEMS</span>
          <span className="brand-title">navigation</span>
          {bounds?.minDate && <span className="brand-range">{bounds.minDate} &rarr; {bounds.maxDate}</span>}
        </div>
        <div className="filters inline">
          <div className="search">
            {terms.map(t => (
              <span className="chip" key={t}>{t}<button onClick={() => setTerms(terms.filter(x => x !== t))}>&times;</button></span>
            ))}
            <input value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={addTerm}
              placeholder={terms.length ? '' : 'Search target, path, user, volume…'} />
          </div>
          {terms.length > 1 && (
            <div className="mode-toggle">
              <button className={mode === 'or' ? 'on' : ''} onClick={() => setMode('or')}>ANY</button>
              <button className={mode === 'and' ? 'on' : ''} onClick={() => setMode('and')}>ALL</button>
            </div>
          )}
          <select className="vol-select" value={source} onChange={e => setSource(e.target.value)}>
            <option value="">All sources</option>
            {SOURCES.map(s => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
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
          brand={['SHELL ITEMS', 'navigation']}
          message={loadMsg} />
        <div className="dash-left">
          <section className="hm-section">
            <SourceTimeline timeline={timeline} selectedDay={selectedDay}
              onSelectDay={(d) => { setOpenItem(null); setSelectedDay(d) }} />
          </section>

          <DaySection day={selectedDay} detail={dayDetail} loading={dayLoading} activity={dayActivity}
            onOpenItem={setOpenItem} onPickHour={setOpenHour} />

          <AllItemsSection filterArgs={filterArgs} onOpenItem={setOpenItem} />
        </div>

        {/* The detail modal used to live inside DaySection, which returns
            early when no day is selected - so opening a record from an
            insight closed the insight panel and showed nothing at all. It
            is not part of a day, so it renders here. */}
        {openItem !== null && openItem !== undefined && (
          <div className="modal-overlay" onClick={() => setOpenItem(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <ItemDetailPanel detail={itemDetail} loading={itemLoading} onClose={() => setOpenItem(null)} />
            </div>
          </div>
        )}

        {openHour !== null && (
          <div className="modal-overlay" onClick={() => setOpenHour(null)}>
            <div className="modal-card" onClick={(e) => e.stopPropagation()}>
              <HourDetailPanel hour={openHour} day={selectedDay} detail={dayDetail}
                onOpenItem={(id) => { setOpenHour(null); setOpenItem(id) }}
                onClose={() => setOpenHour(null)} />
            </div>
          </div>
        )}

        {openInsight && overview?.insights?.[openInsight] ? (
          <InsightPanel
            title={INSIGHT_TITLE[openInsight] || 'Insight'}
            hint={INSIGHT_HINT[openInsight]}
            data={overview.insights[openInsight]}
            onOpen={(id) => { setOpenInsight(null); setOpenItem(id) }}
            onClose={() => setOpenInsight(null)} />
        ) : null}

        <aside className="dash-right">
          <OverviewPanel overview={overview} loading={ovLoading}
            onOpenInsight={setOpenInsight}
            emptyNotes={bounds?.emptyNotes} sourceErrors={bounds?.sourceErrors} />
        </aside>
      </div>
    </div>
  )
}
