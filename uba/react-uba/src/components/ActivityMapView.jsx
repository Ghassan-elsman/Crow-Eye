import { SEVERITY_STYLE } from '../styles/tokens.js'

const SEV_COLOR = { 4: '#ff3b56', 3: '#ff3b56', 2: '#f0a93b', 1: '#4f8eff' }

// Per-day hour heatmap. summary.heatmap = [{day, hour, events, max_severity}]
export default function ActivityMapView({ summary, onCellSelect }) {
  if (!summary || !summary.heatmap) return <p style={{ color: '#8c95ab' }}>No data.</p>
  const cells = summary.heatmap
  const days = [...new Set(cells.map((c) => c.day))].sort().reverse()
  const maxEvents = Math.max(1, ...cells.map((c) => c.events))
  const byKey = Object.fromEntries(cells.map((c) => [`${c.day}|${c.hour}`, c]))

  return (
    <div className="heatmap-wrap">
      <p style={{ color: '#8c95ab', fontSize: 13 }}>
        When activity happened, by hour of day. Brighter cells = more activity;
        color shows the most serious activity in that hour. Click a cell to see it.
      </p>
      {days.map((day) => (
        <div className="heat-row" key={day}>
          <div className="heat-label">{day}</div>
          {Array.from({ length: 24 }, (_, h) => {
            const cell = byKey[`${day}|${h}`]
            const intensity = cell ? 0.25 + 0.75 * (cell.events / maxEvents) : 0
            const color = cell ? SEV_COLOR[cell.max_severity] || '#4f8eff' : null
            return (
              <div key={h} className="heat-cell" title={cell ? `${day} ${h}:00 — ${cell.events} activities` : ''}
                style={cell ? {
                  background: color, opacity: intensity, cursor: 'pointer',
                } : null}
                onClick={cell ? () => onCellSelect({
                  start: `${day} ${String(h).padStart(2, '0')}:00:00`,
                  end: `${day} ${String(h).padStart(2, '0')}:59:59`,
                }) : undefined} />
            )
          })}
        </div>
      ))}
      <div className="heat-axis">
        {Array.from({ length: 24 }, (_, h) => <span key={h}>{h % 3 === 0 ? h : ''}</span>)}
      </div>
    </div>
  )
}
