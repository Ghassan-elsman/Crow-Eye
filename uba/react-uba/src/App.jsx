import { useCallback, useEffect, useRef, useState } from 'react'
import { useBridge } from './hooks/useBridge.js'
import EmptyState from './components/EmptyState.jsx'
import AnalysisProgress from './components/AnalysisProgress.jsx'
import TopBar from './components/TopBar.jsx'
import FilterBar from './components/FilterBar.jsx'
import StorylineView from './components/StorylineView.jsx'
import ActivityMapView from './components/ActivityMapView.jsx'
import CoveragePanel from './components/CoveragePanel.jsx'
import EvidenceModal from './components/EvidenceModal.jsx'

const EMPTY_FILTERS = {
  actors: [], apps: [], classes: [], severities: [], activities: [], search: '',
  start: '', end: '', include_session_user: false,
}

export default function App() {
  const { bridge, callBridge, isLoading, isDev } = useBridge()
  const [status, setStatus] = useState(null)
  const [phase, setPhase] = useState({ percent: 0, label: 'Starting…' })
  const [summary, setSummary] = useState(null)
  const [users, setUsers] = useState([])
  const [apps, setApps] = useState([])
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
    const [u, a, cov] = await Promise.all([
      callBridge('getUsers'), callBridge('getApps'), callBridge('getCoverage')])
    if (u) setUsers(u.users || [])
    if (a) setApps(a.apps || [])
    if (cov) setCoverage(cov)
    refreshSummary(EMPTY_FILTERS)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [callBridge])

  const refreshSummary = useCallback((f) => {
    callBridge('getSummary', JSON.stringify(f)).then((s) => { if (s && !s.pending) setSummary(s) })
  }, [callBridge])

  const onFiltersChange = useCallback((next) => {
    setFilters(next)
    refreshSummary(next)
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
      <TopBar view={view} setView={setView} summary={summary} coverage={coverage} />
      {view !== 'coverage' && (
        <FilterBar filters={filters} onChange={onFiltersChange} users={users}
          apps={apps} summary={summary} />
      )}
      <div className="body">
        <div className="main">
          {view === 'storyline' && (
            <StorylineView filters={filters} summary={summary} callBridge={callBridge}
              onOpenEvidence={setModalEventId} />
          )}
          {view === 'map' && (
            <ActivityMapView summary={summary} onCellSelect={(f) => onFiltersChange({ ...filters, ...f })} />
          )}
          {view === 'coverage' && <CoveragePanel coverage={coverage} />}
        </div>
      </div>
      {modalEventId && (
        <EvidenceModal eventId={modalEventId} callBridge={callBridge}
          onClose={() => setModalEventId(null)} bridge={bridge} />
      )}
    </div>
  )
}
