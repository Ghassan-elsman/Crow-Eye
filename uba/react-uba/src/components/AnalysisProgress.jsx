export default function AnalysisProgress({ phase }) {
  return (
    <div className="center-screen">
      <h2>Building the activity picture…</h2>
      <div className="progress-wrap">
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${phase.percent}%` }} />
        </div>
        <div className="progress-label" style={phase.error ? { color: '#ff3b56' } : null}>
          {phase.label}
        </div>
      </div>
    </div>
  )
}
