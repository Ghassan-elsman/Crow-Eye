import logo from '../assets/crow-eye-logo.png'

const VIEWS = [
  { id: 'storyline', label: 'Activity Story' },
  { id: 'map', label: 'Activity Map' },
  { id: 'coverage', label: 'What we can see' },
]

export default function TopBar({ view, setView, summary, coverage }) {
  const total = summary
    ? (summary.by_class || []).reduce((a, c) => a + c.events, 0)
    : 0
  const gaps = coverage ? coverage.counts.degraded + coverage.counts.unavailable : 0

  return (
    <div className="topbar">
      <div className="tb-brand">
        <span className="logo-badge">
          <img src={logo} alt="Crow-Eye" />
        </span>
        <div className="tb-titles">
          <h1><span className="eye">Crow-Eye</span> UBA</h1>
          <div className="tb-sub">User behavior — what the person did, and what the computer did</div>
        </div>
      </div>

      <div className="viewswitch">
        {VIEWS.map((v) => (
          <button key={v.id} className={view === v.id ? 'active' : ''}
            onClick={() => setView(v.id)}>
            {v.label}
            {v.id === 'coverage' && gaps > 0 && (
              <span className="tab-badge">{gaps}</span>
            )}
          </button>
        ))}
      </div>

      <div className="tb-right">
        {summary && (
          <span className="tb-stat">
            <strong>{total.toLocaleString()}</strong> events
          </span>
        )}
      </div>
    </div>
  )
}
