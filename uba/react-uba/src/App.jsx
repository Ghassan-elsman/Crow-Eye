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
import EvidenceModal from './components/EvidenceModal.jsx'

const EMPTY_FILTERS = {
  actors: [], apps: [], rules: [], classes: [], severities: [], activities: [],
  confidences: [], search: '', start: '', end: '', include_session_user: false,
  order: 'desc',
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
  const started = useRef(false)

  // Wire bridge signals
  useEffect(() => {
    if (!bridge) return
    if (bridge.analysisProgress)
      bridge.analysisProgress.connect((p, l) => setPhase({ percent: p, label: l }))
    if (bridge.analysisComplete)
      bridge.analysisComplete.connect(() => refreshAfterAnalysis())
    if (bridge.analysisError)
      bridge.analysisError.connect((e) => setPhase({ percent: 0, label: 'Error: ' + e, error: true }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bridge])

  // Initial status
  useEffect(() => {
    if (isLoading) return
    if (isDev) { setStatus({ dev: true, parsed_data_available: false, databases: {} }); return }
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
      if (s && !s.pending) { setSummary(s); setBaseSummary(s) }
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callBridge])

  const refreshSummary = useCallback((f) => {
    callBridge('getSummary', JSON.stringify(f)).then((s) => { if (s && !s.pending) setSummary(s) })
  }, [callBridge])

  const onFiltersChange = useCallback((next) => {
    setFilters(next)
    refreshSummary(next)
  }, [refreshSummary])

  // From the Sign-ins view: narrow the story to one session's window and go
  // there, so "what happened while they were signed in" is one click.
  const focusWindow = useCallback((start, end) => {
    const next = { ...EMPTY_FILTERS, start, end, order: 'asc' }
    setFilters(next)
    refreshSummary(next)
    setView('storyline')
  }, [refreshSummary])

  // From the coverage panel: show only this rule's findings.
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
      {view !== 'coverage' && view !== 'signins' && (
        <FilterBar filters={filters} onChange={onFiltersChange} users={users}
          apps={apps} rules={rules} summary={summary} />
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
        </div>
      </div>
      {modalEventId && (
        <EvidenceModal eventId={modalEventId} callBridge={callBridge}
          onClose={() => setModalEventId(null)} bridge={bridge} />
      )}
    </div>
  )
}
