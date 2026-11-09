import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ActivityCard from './ActivityCard.jsx'
import TimelineRail from './TimelineRail.jsx'
import DayStrip from './DayStrip.jsx'
import {
  END_BASIS_STYLE, END_BASIS_NOTE, logonTypeLabel, durationLabel, DRIVER_GROUPS,
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
  filters, summary, railSummary, sessions, callBridge, callAsync, onOpenEvidence, onFiltersChange,
  onOpenDrivers, onOpenDriversDay,
}) {
  // The story's pages and day cards run off Crow-Eye's GUI thread when the
  // bridge offers it (uba_bridge ASYNC_SLOTS); the mock has only callBridge.
  const read = callAsync || callBridge
  const [events, setEvents] = useState([])
  const [cursor, setCursor] = useState(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [timeless, setTimeless] = useState([])
  const [expandedIds, setExpandedIds] = useState(() => new Set())
  const [collapsedSessions, setCollapsedSessions] = useState(() => new Set())
  // People first: what the computer did by itself sits behind one switch, and
  // the switch always says how much it holds (2026-11-03).
  const [showComputer, setShowComputer] = useState(false)
  const reqId = useRef(0)
  // The Activity timeline hides the computer's own background work by default,
  // so a single page can arrive with few visible rows. Pull more pages until at
  // least MIN_SHOWN activities are on screen, capped so a case that is almost
  // all system activity does not page forever.
  const MIN_SHOWN = 50
  const autoPages = useRef(0)

  const toggle = useCallback((id) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }, [])

  // From the day strip: open the card (or folded line) and bring it into view.
  const pick = useCallback((id) => {
    setExpandedIds((prev) => new Set(prev).add(id))
    setTimeout(() => {
      const el = document.getElementById('story-' + id)
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 50)
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
    const query = { ...filters, page_size: 100, grouped: true }
    if (!reset && cursor) query.cursor = cursor
    const res = await read('getBehaviorEvents', JSON.stringify(query))
    if (id !== reqId.current || !res || res.pending) { setLoading(false); return }
    setEvents((prev) => (reset ? res.events : [...prev, ...res.events]))
    setCursor(res.next_cursor)
    setTotal(res.total)
    setLoading(false)
  }, [filters, cursor, read])

  useEffect(() => {
    autoPages.current = 0
    setCursor(null)
    load(true)
    let live = true
    read('getBehaviorEvents', JSON.stringify({ ...filters, timeless: true, page_size: 500 }))
      .then((r) => { if (live && r && !r.pending) setTimeless(r.events) })
    return () => { live = false }
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

  const isComputer = (e) => e.behavior_class === 'system' || e.behavior_class === 'system_app'
  const hiddenCount = useMemo(
    () => events.reduce((n, e) => n + (isComputer(e) ? (e.count || 1) : 0), 0), [events])
  const shown = useMemo(
    () => (showComputer ? events : events.filter((e) => !isComputer(e))), [events, showComputer])

  // Keep the first view useful: while fewer than MIN_SHOWN activities are
  // visible and there are more pages, fetch the next one (up to the cap).
  useEffect(() => {
    if (!loading && cursor && shown.length < MIN_SHOWN && autoPages.current < 20) {
      autoPages.current += 1
      load(false)
    }
  }, [shown.length, cursor, loading, load])

  // Group by day, then by the session covering each run of events inside it.
  const groups = useMemo(() => {
    const out = []
    let day = null
    let band = null
    for (const e of shown) {
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
  }, [shown, sessionFor])

  const ascending = (filters.order || 'desc') === 'asc'

  return (
    <div>
      {summary && <StatTiles summary={summary}
        onPick={(patch) => onFiltersChange && onFiltersChange({ ...filters, ...patch })} />}
      {railSummary && onFiltersChange && (
        <TimelineRail summary={railSummary} filters={filters} onChange={onFiltersChange} />
      )}
      <Legend onDrivers={onOpenDrivers} />
      {hiddenCount > 0 || showComputer ? (
        <button className="computer-toggle" onClick={() => setShowComputer((v) => !v)}>
          {showComputer
            ? 'Hide what the computer did by itself'
            : `Show what the computer did by itself (${hiddenCount.toLocaleString()} in this page)`}
        </button>
      ) : null}

      {events.length === 0 && !loading && (
        <p className="empty-hint">No activity matches these filters.</p>
      )}

      {groups.map((g) => (
        <div key={g.day || 'unknown'}>
          <div className="day-header">{dayLabel(g.day)}</div>
          {g.day && <DaySummary day={g.day} filters={filters} callBridge={read}
            onOpen={(id) => onOpenEvidence && onOpenEvidence(id)}
            onWhoDrove={onOpenDriversDay ? () => onOpenDriversDay(g.day) : null} />}
          <DayStrip items={g.bands.flatMap((b) => b.items)} onPick={pick}
            partial={Boolean(cursor) && g === groups[groups.length - 1]} />
          {g.bands.map((b, bi) => (
            <SessionBand key={b.key || `none-${bi}`} band={b}
              collapsed={collapsedSessions.has(`${g.day}|${b.key}`)}
              onToggle={() => toggleSession(`${g.day}|${b.key}`)}>
              <div className="timeline">
                {b.items.map((e, idx) => (e.kind === 'group' ? (
                  <GroupCard key={'g' + e.event_ids[0]} group={e}
                    expanded={expandedIds.has('g' + e.event_ids[0])}
                    onToggle={() => toggle('g' + e.event_ids[0])}
                    expandedIds={expandedIds} onToggleMember={toggle}
                    onOpenFull={onOpenEvidence} />
                ) : (
                  <ActivityCard key={e.event_id} event={e}
                    isLast={idx === b.items.length - 1}
                    expanded={expandedIds.has(e.event_id)}
                    onToggle={toggle} onOpenFull={onOpenEvidence} />
                )))}
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

// The opening card of a day: who was here and when, what was new, what needs a
// look, and how much the computer did by itself. Every line opens its events.
function DaySummary({ day, filters, callBridge, onOpen, onWhoDrove }) {
  const [card, setCard] = useState(null)
  const person = (filters.actor_sids && filters.actor_sids[0]) || (filters.actors && filters.actors[0]) || ''
  useEffect(() => {
    let live = true
    callBridge('getDaySummary', JSON.stringify({ day, person }))
      .then((r) => { if (live && r && !r.pending) setCard(r) })
    return () => { live = false }
  }, [day, person, callBridge])
  if (!card || !card.lines || card.lines.length === 0) return null
  return (
    <div className="day-summary">
      <div className="ds-title">The day in short</div>
      <ul>
        {card.lines.map((l, i) => (
          <li key={i}>
            {l.event_ids && l.event_ids.length === 1 && onOpen ? (
              <button className="ds-link" onClick={() => onOpen(l.event_ids[0])}>{l.text}</button>
            ) : onWhoDrove && /^Who drove it/.test(l.text) ? (
              <button className="ds-link" onClick={onWhoDrove} title="Open this day on the Who drove it tab">{l.text}</button>
            ) : <span>{l.text}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

// Alike activity folded into one line; opening it shows every activity it
// stands for, each with its own proof.
function GroupCard({ group, expanded, onToggle, expandedIds, onToggleMember, onOpenFull }) {
  const lead = (group.members && group.members[0]) || {}
  const shown = { ...lead, event_id: 'g' + group.event_ids[0], description: group.text,
    severity: group.severity, aggregate_count: group.count, ts_start: group.ts_start,
    ts_end: group.ts_end, evidence: [], details: {} }
  return (
    <div className="group-card" id={'story-g' + group.event_ids[0]}>
      <div role="button" tabIndex={0} onClick={onToggle}
        onKeyDown={(e) => { if (e.key === 'Enter') onToggle() }}>
        <ActivityCard event={shown} expanded={false} onToggle={onToggle} onOpenFull={() => onToggle()} />
      </div>
      {expanded && (
        <div className="timeline group-members">
          {(group.members || []).map((m, idx) => (
            <ActivityCard key={m.event_id} event={m}
              isLast={idx === group.members.length - 1}
              expanded={expandedIds.has(m.event_id)}
              onToggle={onToggleMember} onOpenFull={onOpenFull} />
          ))}
        </div>
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

// Each tile opens what it counts: the same class or severity filter.
function StatTiles({ summary, onPick }) {
  const bySev = Object.fromEntries((summary.by_severity || []).map((s) => [s.severity, s.events]))
  const byClass = Object.fromEntries((summary.by_class || []).map((c) => [c.behavior_class, c.events]))
  const total = (summary.by_class || []).reduce((a, c) => a + c.events, 0)
  const person = byClass.user || 0
  const computer = (byClass.system || 0) + (byClass.system_app || 0) + (byClass.application || 0)
  const flagged = (bySev.suspicious || 0) + (bySev.critical || 0)
  const tiles = [
    { n: total, l: 'Total events', patch: { classes: [], severities: [] } },
    { n: person, l: 'A person did', color: '#4f8eff', patch: { classes: ['user'], severities: [] } },
    { n: computer, l: 'The computer did', color: '#9aa3b8',
      patch: { classes: ['system', 'system_app', 'application'], severities: [] } },
    { n: flagged, l: 'Needs review', color: flagged ? '#ff3b56' : undefined,
      patch: { classes: [], severities: ['suspicious', 'critical'] } },
  ]
  return (
    <div className="tiles">
      {tiles.map((t, i) => (
        <button className="tile tile-btn" key={i} disabled={!onPick || !t.n}
          onClick={() => onPick && onPick(t.patch)} title={t.n ? 'Show these ' + t.n.toLocaleString() : ''}>
          <div className="n" style={t.color ? { color: t.color } : null}>{t.n.toLocaleString()}</div>
          <div className="l">{t.l}</div>
        </button>
      ))}
    </div>
  )
}

// The dots say who drove a step (who_drove.py); each opens those steps.
function Legend({ onDrivers }) {
  // One entry per Driven-by toggle, in its colour (tokens ACTOR_COLOR).
  const items = DRIVER_GROUPS.map((g) => ({ key: g.key, label: g.label, color: g.color, drivers: g.drivers }))
  return (
    <div className="legend">
      {items.map((l) => (
        <button key={l.key} className="legend-item legend-btn" disabled={!onDrivers}
          onClick={() => onDrivers && onDrivers({ drivers: l.drivers })} title={'Show only: ' + l.label}>
          <span className="legend-dot" style={{ background: l.color }} />
          <span>{l.label}</span>
        </button>
      ))}
      <div className="legend-item">
        <span className="legend-dot" style={{ background: '#ff3b56' }} />
        <span>Flagged — needs analyst review</span>
      </div>
    </div>
  )
}
