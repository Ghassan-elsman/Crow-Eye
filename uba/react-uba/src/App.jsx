import { useCallback, useEffect, useRef, useState } from 'react'
import { useBridge } from './hooks/useBridge.js'
import EmptyState from './components/EmptyState.jsx'
import AnalysisProgress from './components/AnalysisProgress.jsx'
import TopBar from './components/TopBar.jsx'
import FilterBar from './components/FilterBar.jsx'
import StorylineView from './components/StorylineView.jsx'
import ActivityMapView from './components/ActivityMapView.jsx'
import SignInsView from './components/SignInsView.jsx'
import CoveragePanel from './components/CoveragePanel.jsx'
import RulesView from './components/RulesView.jsx'
import EvidenceModal from './components/EvidenceModal.jsx'

// actor_sids: the person key (one SID matches every name that person had).
// Set by an initial filter from another window, or by picking a user chip.
const EMPTY_FILTERS = {
  actors: [], actor_sids: [], apps: [], rules: [], classes: [], severities: [],
  activities: [], confidences: [], search: '', start: '', end: '',
  include_session_user: false, order: 'desc',
}

// An initial filter from the bridge (getInitialFilter / initialFilterChanged:
// the Behaviour Results view's "Open in User Behavior") as a filter state.
// Everything else starts clear, oldest first, so the window reads as the
// story of that person in that time range.
function filtersFromInitial(f) {
  return {
    ...EMPTY_FILTERS,
    actor_sids: Array.isArray(f.actor_sids) ? f.actor_sids.filter(Boolean) : [],
    actors: Array.isArray(f.actors) ? f.actors : [],
    start: f.start || '',
    end: f.end || '',
    order: 'asc',
  }
}

export default function App() {
  const { bridge, callBridge, isLoading, isDev } = useBridge()
  const [status, setStatus] = useState(null)
  const [phase, setPhase] = useState({ percent: 0, label: 'Starting…' })
  const [summary, setSummary] = useState(null)
  // The unfiltered summary, kept so the day rail always shows the WHOLE case.
  // Built from the filtered one it would collapse to the single selected day,
  // and picking a day would remove the means of picking another.
  const [baseSummary, setBaseSummary] = useState(null)
  const [users, setUsers] = useState([])
  const [apps, setApps] = useState([])
  const [rules, setRules] = useState([])
  const [sessionsReport, setSessionsReport] = useState(null)
  const [coverage, setCoverage] = useState(null)
  const [view, setView] = useState('storyline')
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [modalEventId, setModalEventId] = useState(null)
  // Bumped when the Behaviour Rule Creator saves or deletes a rule, so the
  // Rules view reads the list again.
  const [rulesVersion, setRulesVersion] = useState(0)
  const started = useRef(false)
  const rerunRef = useRef(null)
  // Where the current filter came from ("Behaviour Results: ..."), shown in
  // the filter bar until the analyst clears it. Cleared by any filter change
  // that removes the person and the time range.
  const [origin, setOrigin] = useState('')
  // The filters as they are now, for callbacks wired once (bridge signals,
  // the post-analysis refresh), and the last initial-filter seq applied.
  const filtersRef = useRef(EMPTY_FILTERS)
  const appliedSeq = useRef(0)
  const analysedRef = useRef(false)
  filtersRef.current = filters

  // Wire bridge signals
  useEffect(() => {
    if (!bridge) return
    if (bridge.analysisProgress)
      bridge.analysisProgress.connect((p, l) => setPhase({ percent: p, label: l }))
    if (bridge.analysisComplete)
      bridge.analysisComplete.connect(() => refreshAfterAnalysis())
    if (bridge.analysisError)
      bridge.analysisError.connect((e) => setPhase({ percent: 0, label: 'Error: ' + e, error: true }))
    // Another window asked again with a new filter (the window stays open).
    if (bridge.initialFilterChanged)
      bridge.initialFilterChanged.connect((json) => {
        let info = {}
        try { info = JSON.parse(json) || {} } catch { info = {} }
        applyInitialRef.current(info)
      })
    // The Behaviour Rule Creator (a Qt window) saved or deleted a rule.
    if (bridge.rulesChanged)
      bridge.rulesChanged.connect((json) => {
        let info = {}
        try { info = JSON.parse(json) || {} } catch { info = {} }
        setRulesVersion((v) => v + 1)
        if (info.rerun && rerunRef.current) rerunRef.current()
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bridge])

  // Initial status
  useEffect(() => {
    if (isLoading) return
    if (isDev) { setStatus({ dev: true, parsed_data_available: false, databases: {} }); return }
    // An initial filter first, so the first summary and story are already
    // the filtered ones. Held in state while the analysis runs.
    callBridge('getInitialFilter').then((info) => { if (info) applyInitialRef.current(info) })
      .catch(() => {})
    callBridge('getStatus').then((s) => {
      setStatus(s)
      if (s && s.parsed_data_available && !s.analysis_done && !started.current) {
        started.current = true
        callBridge('startAnalysis')
      } else if (s && s.analysis_done) {
        refreshAfterAnalysis()
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, isDev])

  const refreshAfterAnalysis = useCallback(async () => {
    analysedRef.current = true
    setStatus((prev) => ({ ...(prev || {}), analysis_done: true, parsed_data_available: true }))
    const [u, a, r, sess, cov] = await Promise.all([
      callBridge('getUsers'), callBridge('getApps'), callBridge('getRules'),
      callBridge('getSessions'), callBridge('getCoverage')])
    if (u) setUsers(u.users || [])
    if (a) setApps(a.apps || [])
    if (r && !r.pending) setRules(r.rules || [])
    if (sess && !sess.pending) setSessionsReport(sess)
    if (cov) setCoverage(cov)
    callBridge('getSummary', JSON.stringify(EMPTY_FILTERS)).then((s) => {
      if (s && !s.pending) { setBaseSummary(s); setSummary(s) }
      // A filter set before the analysis finished (an initial filter): its
      // own summary, after the whole-case one, so the tiles match the story.
      const f = filtersRef.current
      if (f !== EMPTY_FILTERS) {
        callBridge('getSummary', JSON.stringify(f)).then((fs) => {
          if (fs && !fs.pending) setSummary(fs)
        })
      }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callBridge])

  const refreshSummary = useCallback((f) => {
    callBridge('getSummary', JSON.stringify(f)).then((s) => { if (s && !s.pending) setSummary(s) })
  }, [callBridge])

  const onFiltersChange = useCallback((next) => {
    setFilters(next)
    refreshSummary(next)
    if (!(next.actor_sids || []).length && !next.start && !next.end) setOrigin('')
  }, [refreshSummary])

  // {"filter": {...} | null, "seq": n}: apply each seq once. A null filter
  // (the opener asked for no narrowing) clears what an earlier one set.
  const applyInitial = useCallback((info) => {
    if (!info || typeof info.seq !== 'number' || info.seq <= appliedSeq.current) return
    appliedSeq.current = info.seq
    const next = info.filter ? filtersFromInitial(info.filter) : EMPTY_FILTERS
    // Now, not at the next render: the post-analysis refresh may read it first.
    filtersRef.current = next
    setFilters(next)
    setOrigin(info.filter ? (info.filter.label || 'another window') : '')
    setView('storyline')
    if (analysedRef.current) refreshSummary(next)
  }, [refreshSummary])
  const applyInitialRef = useRef(applyInitial)
  applyInitialRef.current = applyInitial

  // From the Sign-ins view: narrow the story to one session's window and go
  // there, so "what happened while they were signed in" is one click.
  const focusWindow = useCallback((start, end) => {
    const next = { ...EMPTY_FILTERS, start, end, order: 'asc' }
    setFilters(next)
    refreshSummary(next)
    setView('storyline')
  }, [refreshSummary])

  // From the coverage panel: show only this rule's findings.
  // From the Rules view: analyse again with the switches as now saved. The
  // progress screen shows while it runs; analysisComplete brings the views back.
  const rerunAnalysis = useCallback(() => {
    setPhase({ percent: 0, label: 'Starting…' })
    setStatus((prev) => ({ ...(prev || {}), analysis_done: false }))
    callBridge('rerunAnalysis')
  }, [callBridge])
  rerunRef.current = rerunAnalysis

  const focusRule = useCallback((ruleId) => {
    const next = { ...EMPTY_FILTERS, rules: [ruleId] }
    setFilters(next)
    refreshSummary(next)
    setView('storyline')
  }, [refreshSummary])

  if (isLoading || !status) {
    return <div className="center-screen"><p>Connecting…</p></div>
  }
  if (!status.parsed_data_available && !status.analysis_done) {
    return <EmptyState status={status} isDev={isDev} />
  }
  if (!status.analysis_done) {
    return <AnalysisProgress phase={phase} />
  }

  return (
    <div className="uba-app">
      <TopBar view={view} setView={setView} summary={summary} coverage={coverage}
        sessionsReport={sessionsReport} />
      {view !== 'coverage' && view !== 'signins' && view !== 'rules' && (
        <FilterBar filters={filters} onChange={onFiltersChange} users={users}
          apps={apps} rules={rules} summary={summary} origin={origin}
          onClearOrigin={() => onFiltersChange({ ...filters, actor_sids: [], actors: [], start: '', end: '' })} />
      )}
      <div className="body">
        <div className="main">
          {view === 'storyline' && (
            <StorylineView filters={filters} summary={summary} callBridge={callBridge}
              railSummary={baseSummary || summary}
              sessions={sessionsReport ? sessionsReport.sessions : []}
              onFiltersChange={onFiltersChange}
              onOpenEvidence={setModalEventId} />
          )}
          {view === 'map' && (
            <ActivityMapView summary={summary} onCellSelect={(f) => onFiltersChange({ ...filters, ...f })} />
          )}
          {view === 'signins' && (
            <SignInsView report={sessionsReport} onFocusWindow={focusWindow} />
          )}
          {view === 'coverage' && (
            <CoveragePanel coverage={coverage} rules={rules} onFocusRule={focusRule} />
          )}
          {view === 'rules' && (
            <RulesView callBridge={callBridge} onRerun={rerunAnalysis} refreshKey={rulesVersion} />
          )}
        </div>
      </div>
      {modalEventId && (
        <EvidenceModal eventId={modalEventId} callBridge={callBridge}
          onClose={() => setModalEventId(null)} bridge={bridge} />
      )}
    </div>
  )
}
