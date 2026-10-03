import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ActivityCard from './ActivityCard.jsx'
import TimelineRail from './TimelineRail.jsx'
import {
  END_BASIS_STYLE, END_BASIS_NOTE, logonTypeLabel, durationLabel,
} from '../styles/tokens.js'

function dayLabel(ts) {
  if (!ts) return ''
  const d = new Date(ts.replace(' ', 'T') + 'Z')
  if (isNaN(d)) return ts.slice(0, 10)
  return d.toLocaleDateString(undefined, {
    weekday: 'long', year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC',
  })
}

export default function StorylineView({
  filters, summary, railSummary, sessions, callBridge, onOpenEvidence, onFiltersChange,
}) {
  const [events, setEvents] = useState([])
  const [cursor, setCursor] = useState(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [timeless, setTimeless] = useState([])
  const [expandedIds, setExpandedIds] = useState(() => new Set())
  const [collapsedSessions, setCollapsedSessions] = useState(() => new Set())
  const reqId = useRef(0)

  const toggle = useCallback((id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }, [])

  const toggleSession = useCallback((key) => {
    setCollapsedSessions((prev) => {
      const next = new Set(prev)
      next.has(key) ? next.delete(key) : next.add(key)
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

  // Sessions sorted by start, so the covering session for a moment is the last
  // one that began at or before it. Sign-in sessions are context, never proof of
  // who acted — the band says "signed in", the cards keep their own attribution.
  const sessionList = useMemo(
    () => [...(sessions || [])].sort((a, b) => (a.start_ts < b.start_ts ? -1 : 1)),
    [sessions])

  const sessionFor = useCallback((ts) => {
    if (!ts || sessionList.length === 0) return null
    let found = null
    for (const s of sessionList) {
      if (s.start_ts > ts) break
      const end = s.end_ts || s.context_end_ts
      if (!end || end >= ts) found = s
    }
    return found
  }, [sessionList])

  // Group by day, then by the session covering each run of events inside it.
  const groups = useMemo(() => {
    const out = []
    let day = null
    let band = null
    for (const e of events) {
      const d = (e.ts_start || '').slice(0, 10)
      if (!day || day.day !== d) {
        day = { day: d, bands: [] }
        out.push(day)
        band = null
      }
      const session = sessionFor(e.ts_start)
      const key = session ? `${session.username}|${session.start_ts}` : ''
      if (!band || band.key !== key) {
        band = { key, session, items: [] }
        day.bands.push(band)
      }
      band.items.push(e)
    }
    return out
  }, [events, sessionFor])

  const ascending = (filters.order || 'desc') === 'asc'

  return (
    <div>
      {summary && <StatTiles summary={summary} />}
      {railSummary && onFiltersChange && (
        <TimelineRail summary={railSummary} filters={filters} onChange={onFiltersChange} />
      )}
      <Legend />

      {events.length === 0 && !loading && (
        <p className="empty-hint">No activity matches these filters.</p>
      )}

      {groups.map((g) => (
        <div key={g.day || 'unknown'}>
          <div className="day-header">{dayLabel(g.day)}</div>
          {g.bands.map((b, bi) => (
            <SessionBand key={b.key || `none-${bi}`} band={b}
              collapsed={collapsedSessions.has(`${g.day}|${b.key}`)}
              onToggle={() => toggleSession(`${g.day}|${b.key}`)}>
              <div className="timeline">
                {b.items.map((e, idx) => (
                  <ActivityCard key={e.event_id} event={e}
                    isLast={idx === b.items.length - 1}
                    expanded={expandedIds.has(e.event_id)}
                    onToggle={toggle} onOpenFull={onOpenEvidence} />
                ))}
              </div>
            </SessionBand>
          ))}
        </div>
      ))}

      {cursor && (
        <button className="load-more" onClick={() => load(false)} disabled={loading}>
          {loading ? 'Loading…'
            : `Show ${ascending ? 'later' : 'earlier'} activity (${events.length} of ${total})`}
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

// A run of activity that happened while one account was signed in. Collapsible,
// because on a long case the band header is the fastest way to scan who was at
// the machine when.
function SessionBand({ band, collapsed, onToggle, children }) {
  const s = band.session
  if (!s) {
    return (
      <div className="sb sb-none">
        <div className="sb-head plain">
          <span className="sb-dim">
            No sign-in session covers this activity — nobody is known to have been
            signed in at the time.
          </span>
        </div>
        {children}
      </div>
    )
  }
  const end = END_BASIS_STYLE[s.end_basis] || END_BASIS_STYLE.open
  return (
    <div className={'sb' + (s.is_open ? ' sb-open' : '')}>
      <div className="sb-head" role="button" tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => { if (e.key === 'Enter') onToggle() }}>
        <span className="sb-chevron" style={{ transform: collapsed ? 'rotate(-90deg)' : 'none' }}>▾</span>
        <strong className="sb-user">{s.username}</strong>
        <span className="sb-dim">was signed in</span>
        <span className="sb-mono">{(s.start_ts || '').slice(11, 16)}</span>
        <span className="sb-arrow">→</span>
        <span className="sb-mono">
          {s.end_ts ? s.end_ts.slice(11, 16) : <span className="sb-unknown">?</span>}
        </span>
        {s.duration_seconds !== null && (
          <span className="sb-dur">{durationLabel(s.duration_seconds)}</span>
        )}
        <span className="pill" style={{ color: end.color, background: `${end.color}22` }}
          title={END_BASIS_NOTE[s.end_basis] || ''}>
          {end.label}
        </span>
        <span className="sb-dim sb-type">{logonTypeLabel(s.logon_type)}</span>
        {s.unlock_count > 0 && (
          <span className="count-pill" title="Times the screen was unlocked during this session">
            {s.unlock_count} unlock{s.unlock_count === 1 ? '' : 's'}
          </span>
        )}
        <span className="sb-count">{band.items.length} activities here</span>
      </div>
      {!collapsed && children}
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
