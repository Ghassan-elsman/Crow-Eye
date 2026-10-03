import { useMemo } from 'react'

// Severity -> bar colour. Matches ActivityMapView so the two views agree.
const SEV_COLOR = { 4: '#ff3b56', 3: '#ff3b56', 2: '#f0a93b', 1: '#4f8eff' }
const RAIL_H = 42

function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00Z')
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

function dayLabel(iso) {
  const d = new Date(iso + 'T00:00:00Z')
  if (isNaN(d)) return iso
  return d.toLocaleDateString(undefined, {
    weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC',
  })
}

/**
 * One bar per day across the whole case, so a case spanning weeks can be
 * navigated instead of paged through. The storyline serves 200 events at a time
 * newest-first; on a 48-day case that is ~44 presses of "Show more" to reach the
 * beginning, with no way to land on a particular day.
 *
 * Built entirely from summary.heatmap, which the backend already returns.
 */
export default function TimelineRail({ summary, filters, onChange }) {
  const days = useMemo(() => {
    const cells = (summary && summary.heatmap) || []
    if (cells.length === 0) return []
    const totals = new Map()
    for (const c of cells) {
      const prev = totals.get(c.day) || { events: 0, max: 1 }
      totals.set(c.day, {
        events: prev.events + c.events,
        max: Math.max(prev.max, c.max_severity || 1),
      })
    }
    // Walk the calendar, not just the days that have data, so gaps in activity
    // are visible as gaps rather than silently closing up.
    const keys = [...totals.keys()].sort()
    const out = []
    let cursor = keys[0]
    const last = keys[keys.length - 1]
    let guard = 0
    while (cursor <= last && guard++ < 800) {
      const hit = totals.get(cursor)
      out.push({ day: cursor, events: hit ? hit.events : 0, max: hit ? hit.max : 0 })
      cursor = addDays(cursor, 1)
    }
    return out
  }, [summary])

  if (days.length <= 1) return null

  const maxEvents = Math.max(1, ...days.map((d) => d.events))
  const active = days.filter((d) => d.events > 0).length
  // Square-root scale. A case usually has a few outlier days holding thousands
  // of events and a long tail holding a handful; on a linear scale the tail
  // rounds to nothing and the rail reads as empty even though those days are
  // exactly the ones worth finding.
  const barHeight = (n) => (n ? Math.max(4, Math.round(RAIL_H * Math.sqrt(n / maxEvents))) : 2)
  // Which day (if any) the current time filter has narrowed to.
  const selected = filters.start && filters.end
    && filters.start.slice(0, 10) === filters.end.slice(0, 10)
    ? filters.start.slice(0, 10) : null

  const pick = (day) => {
    if (selected === day) {
      return onChange({ ...filters, start: '', end: '' })   // toggle off
    }
    onChange({ ...filters, start: `${day} 00:00:00`, end: `${day} 23:59:59` })
  }

  const busiest = days.reduce((a, b) => (b.events > a.events ? b : a), days[0])

  return (
    <div className="rail">
      <div className="rail-head">
        <span className="rail-title">Jump to a day</span>
        <span className="rail-hint">
          {days.length} days, {active} with activity · busiest {dayLabel(busiest.day)}
          {' '}({busiest.events.toLocaleString()})
          {selected && ` · showing ${dayLabel(selected)} only`}
        </span>
        {selected && (
          <button className="rail-clear" onClick={() => onChange({ ...filters, start: '', end: '' })}>
            Show all days
          </button>
        )}
      </div>
      <div className="rail-bars">
        {days.map((d) => {
          const height = barHeight(d.events)
          const color = d.events ? (SEV_COLOR[d.max] || '#4f8eff') : 'var(--border)'
          return (
            <button key={d.day} type="button"
              className={'rail-bar' + (selected === d.day ? ' on' : '')
                + (d.events === 0 ? ' empty' : '')}
              title={d.events
                ? `${dayLabel(d.day)} — ${d.events.toLocaleString()} activities`
                : `${dayLabel(d.day)} — no activity recorded`}
              aria-label={`${d.day}, ${d.events} activities`}
              onClick={() => pick(d.day)}>
              <span className="rail-fill" style={{ height, background: color }} />
            </button>
          )
        })}
      </div>
      <div className="rail-axis">
        <span>{dayLabel(days[0].day)}</span>
        <span>{dayLabel(days[days.length - 1].day)}</span>
      </div>
    </div>
  )
}
