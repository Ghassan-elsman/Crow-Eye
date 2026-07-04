import { useCallback, useEffect, useRef, useState } from 'react'
import ActivityCard from './ActivityCard.jsx'

function dayLabel(ts) {
  if (!ts) return ''
  const d = new Date(ts.replace(' ', 'T') + 'Z')
  if (isNaN(d)) return ts.slice(0, 10)
  return d.toLocaleDateString(undefined, {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC',
  })
}

export default function StorylineView({ filters, summary, callBridge, onOpenEvidence }) {
  const [events, setEvents] = useState([])
  const [cursor, setCursor] = useState(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [timeless, setTimeless] = useState([])
  const [expandedIds, setExpandedIds] = useState(() => new Set())
  const reqId = useRef(0)

  const toggle = useCallback((id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }, [])

  const load = useCallback(async (reset) => {
    const id = ++reqId.current
    setLoading(true)
    const query = { ...filters, page_size: 200 }
    if (!reset && cursor) query.cursor = cursor
    const res = await callBridge('getBehaviorEvents', JSON.stringify(query))
    if (id !== reqId.current || !res || res.pending) { setLoading(false); return }
    setEvents((prev) => (reset ? res.events : [...prev, ...res.events]))
    setCursor(res.next_cursor)
    setTotal(res.total)
    setLoading(false)
  }, [filters, cursor, callBridge])

  useEffect(() => {
    setCursor(null)
    load(true)
    callBridge('getBehaviorEvents', JSON.stringify({ ...filters, timeless: true, page_size: 500 }))
      .then((r) => { if (r && !r.pending) setTimeless(r.events) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters])

  // Group consecutive events by day
  const groups = []
  let cur = null
  for (const e of events) {
    const day = (e.ts_start || '').slice(0, 10)
    if (!cur || cur.day !== day) { cur = { day, items: [] }; groups.push(cur) }
    cur.items.push(e)
  }

  return (
    <div>
      {summary && <StatTiles summary={summary} />}
      <Legend />

      {events.length === 0 && !loading && (
        <p className="empty-hint">No activity matches these filters.</p>
      )}

      {groups.map((g) => (
        <div key={g.day || 'unknown'}>
          <div className="day-header">{dayLabel(g.day)}</div>
          <div className="timeline">
            {g.items.map((e, idx) => (
              <ActivityCard key={e.event_id} event={e}
                isLast={idx === g.items.length - 1}
                expanded={expandedIds.has(e.event_id)}
                onToggle={toggle} onOpenFull={onOpenEvidence} />
            ))}
          </div>
        </div>
      ))}

      {cursor && (
        <button className="load-more" onClick={() => load(false)} disabled={loading}>
          {loading ? 'Loading…' : `Show more (${events.length} of ${total})`}
        </button>
      )}

      {timeless.length > 0 && (
        <details className="timeless">
          <summary>Activity without an exact time ({timeless.length})</summary>
          <div className="timeline" style={{ marginTop: 10 }}>
            {timeless.map((e, idx) => (
              <ActivityCard key={e.event_id} event={e}
                isLast={idx === timeless.length - 1}
                expanded={expandedIds.has(e.event_id)}
                onToggle={toggle} onOpenFull={onOpenEvidence} />
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

function StatTiles({ summary }) {
  const bySev = Object.fromEntries((summary.by_severity || []).map((s) => [s.severity, s.events]))
  const byClass = Object.fromEntries((summary.by_class || []).map((c) => [c.behavior_class, c.events]))
  const total = (summary.by_class || []).reduce((a, c) => a + c.events, 0)
  const person = byClass.user || 0
  const computer = (byClass.system || 0) + (byClass.system_app || 0) + (byClass.application || 0)
  const flagged = (bySev.suspicious || 0) + (bySev.critical || 0)
  const tiles = [
    { n: total, l: 'Total events' },
    { n: person, l: 'A person did', color: '#4f8eff' },
    { n: computer, l: 'The computer did', color: '#9aa3b8' },
    { n: flagged, l: 'Needs review', color: flagged ? '#ff3b56' : undefined },
  ]
  return (
    <div className="tiles">
      {tiles.map((t, i) => (
        <div className="tile" key={i}>
          <div className="n" style={t.color ? { color: t.color } : null}>{t.n.toLocaleString()}</div>
          <div className="l">{t.l}</div>
        </div>
      ))}
    </div>
  )
}

function Legend() {
  const items = [
    { color: '#4f8eff', label: 'A person at the keyboard' },
    { color: '#9aa3b8', label: 'Automated — the computer, no human input' },
    { color: '#ff3b56', label: 'Flagged — needs analyst review' },
  ]
  return (
    <div className="legend">
      {items.map((l) => (
        <div key={l.label} className="legend-item">
          <span className="legend-dot" style={{ background: l.color }} />
          <span>{l.label}</span>
        </div>
      ))}
    </div>
  )
}
