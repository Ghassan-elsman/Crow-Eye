import { useEffect, useMemo, useRef, useState } from 'react'
import { CLASS_STYLE, SEVERITY_STYLE, CONFIDENCE_TIER } from '../styles/tokens.js'

const CLASSES = ['user', 'application', 'system']
const SEVERITIES = ['routine', 'notable', 'suspicious', 'critical']
const CONFIDENCES = ['corroborated', 'log-only', 'artifact-only', 'presence', 'inference']

function toggle(list, value) {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
}

// 'YYYY-MM-DD HH:MM:SS' (store) <-> 'YYYY-MM-DDTHH:MM' (datetime-local input)
function toInput(store) {
  if (!store) return ''
  return store.slice(0, 16).replace(' ', 'T')
}
function fromInput(val, endOfMinute) {
  if (!val) return ''
  return val.replace('T', ' ') + (endOfMinute ? ':59' : ':00')
}

export default function FilterBar({ filters, onChange, users, apps, rules, summary }) {
  const [search, setSearch] = useState(filters.search)

  useEffect(() => {
    const t = setTimeout(() => {
      if (search !== filters.search) onChange({ ...filters, search })
    }, 300)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search])

  const actorOptions = [
    ...users.map((u) => ({ value: u.username, label: u.username })),
    { value: '', label: 'Unattributed' },
  ]

  const clearTime = () => onChange({ ...filters, start: '', end: '' })

  // Quick time presets derived from the case's overall span.
  const span = summary && summary.time_span
  const applyPreset = (val) => {
    if (!val || !span || !span.start || !span.end) { clearTime(); return }
    if (val === 'all') return clearTime()
    if (val === 'first') {
      const d = span.start.slice(0, 10)
      return onChange({ ...filters, start: `${d} 00:00:00`, end: `${d} 23:59:59` })
    }
    if (val === 'last') {
      const d = span.end.slice(0, 10)
      return onChange({ ...filters, start: `${d} 00:00:00`, end: `${d} 23:59:59` })
    }
    if (val === 'lasthour') {
      const end = span.end
      const dt = new Date(end.replace(' ', 'T') + 'Z')
      dt.setUTCHours(dt.getUTCHours() - 1)
      const start = dt.toISOString().slice(0, 19).replace('T', ' ')
      return onChange({ ...filters, start, end })
    }
  }
  const presetValue = !filters.start && !filters.end ? 'all' : 'custom'

  return (
    <div className="filterbar">
      <input type="search" placeholder="Search activities…" value={search}
        onChange={(e) => setSearch(e.target.value)} />

      {/* ---- User ---- */}
      <div className="filter-group">
        <span className="filter-label">User</span>
        <div className="chiprow">
          {actorOptions.map((a) => (
            <span key={a.value || 'none'}
              className={'chip ' + (filters.actors.includes(a.value) ? 'on' : '')}
              onClick={() => onChange({ ...filters, actors: toggle(filters.actors, a.value) })}>
              {a.label}
            </span>
          ))}
          {filters.actors.length > 0 && (
            <span
              className={'chip ' + (filters.include_session_user ? 'on' : '')}
              title="Also include activity that happened while the selected person was signed in (labelled, not proven)"
              onClick={() => onChange({ ...filters, include_session_user: !filters.include_session_user })}>
              {filters.include_session_user ? '✓ ' : ''}incl. signed-in time
            </span>
          )}
        </div>
      </div>

      {/* ---- App ---- */}
      <div className="filter-group">
        <span className="filter-label">App</span>
        <AppMultiSelect apps={apps}
          selected={filters.apps}
          onChange={(next) => onChange({ ...filters, apps: next })} />
      </div>

      {/* ---- Detection rule ---- */}
      <div className="filter-group">
        <span className="filter-label">Rules</span>
        <RuleSelect rules={rules}
          selected={filters.rules}
          onChange={(next) => onChange({ ...filters, rules: next })} />
      </div>

      {/* ---- Class ---- */}
      <div className="chiprow">
        {CLASSES.map((c) => (
          <span key={c}
            className={'chip ' + (filters.classes.includes(c) ? 'on' : '')}
            style={filters.classes.includes(c) ? { borderColor: CLASS_STYLE[c].color } : null}
            onClick={() => onChange({ ...filters, classes: toggle(filters.classes, c) })}>
            {CLASS_STYLE[c].label}
          </span>
        ))}
      </div>

      {/* ---- Severity ---- */}
      <div className="chiprow">
        {SEVERITIES.map((s) => (
          <span key={s}
            className={'chip ' + (filters.severities.includes(s) ? 'on' : '')}
            style={filters.severities.includes(s) ? { borderColor: SEVERITY_STYLE[s].color, color: SEVERITY_STYLE[s].color } : null}
            onClick={() => onChange({ ...filters, severities: toggle(filters.severities, s) })}>
            {SEVERITY_STYLE[s].label}
          </span>
        ))}
      </div>

      {/* ---- Time range ---- */}
      <div className="filter-group">
        <span className="filter-label">Time</span>
        <select className="preset-select" value={presetValue}
          onChange={(e) => applyPreset(e.target.value)} title="Quick time range">
          <option value="all">All time</option>
          {presetValue === 'custom' && <option value="custom">Custom range</option>}
          <option value="first">First day</option>
          <option value="last">Last day</option>
          <option value="lasthour">Last hour of activity</option>
        </select>
        <input type="datetime-local" value={toInput(filters.start)} title="From"
          onChange={(e) => onChange({ ...filters, start: fromInput(e.target.value, false) })} />
        <span className="range-sep">→</span>
        <input type="datetime-local" value={toInput(filters.end)} title="To"
          onChange={(e) => onChange({ ...filters, end: fromInput(e.target.value, true) })} />
        {(filters.start || filters.end) && (
          <span className="chip" onClick={clearTime} title="Clear time range">Clear</span>
        )}
      </div>

      {/* ---- Certainty ---- */}
      <div className="filter-group">
        <span className="filter-label">Certainty</span>
        <div className="chiprow">
          {CONFIDENCES.map((c) => {
            const tier = CONFIDENCE_TIER[c] || { label: c, color: '#8c95ab' }
            const on = filters.confidences.includes(c)
            return (
              <span key={c} className={'chip ' + (on ? 'on' : '')}
                style={on ? { borderColor: tier.color, color: tier.color } : null}
                title={`Show only activities whose evidence is ${tier.label.toLowerCase()}`}
                onClick={() => onChange({
                  ...filters, confidences: toggle(filters.confidences, c),
                })}>
                {tier.label}
              </span>
            )
          })}
        </div>
      </div>

      {/* ---- Reading order ---- */}
      <div className="filter-group">
        <span className="filter-label">Order</span>
        <select className="preset-select" value={filters.order || 'desc'}
          title="Read the story newest-first or oldest-first"
          onChange={(e) => onChange({ ...filters, order: e.target.value })}>
          <option value="desc">Newest first</option>
          <option value="asc">Oldest first</option>
        </select>
      </div>
    </div>
  )
}

// Detection-rule picker. Same popover shape as AppMultiSelect below, so it
// inherits the existing styling rather than introducing a second pattern.
//
// Each rule shows its event count, which is how a rule that is reported as
// WORKING but found nothing becomes visible — a distinct statement from "no
// data for this rule", and one nothing else in the UI makes.
function RuleSelect({ rules, selected, onChange }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const list = (rules || []).filter((r) => !needle
      || r.title.toLowerCase().includes(needle)
      || r.rule_id.toLowerCase().includes(needle))
    const by = new Map()
    for (const r of list) {
      const key = CLASS_STYLE[r.behavior_class] ? r.behavior_class : 'system'
      if (!by.has(key)) by.set(key, [])
      by.get(key).push(r)
    }
    return [...by.entries()]
  }, [rules, q])

  const withEvents = useMemo(
    () => (rules || []).filter((r) => r.event_count > 0).map((r) => r.rule_id),
    [rules])
  const flagged = useMemo(
    () => (rules || []).filter((r) => r.event_count > 0
      && (r.severity === 'suspicious' || r.severity === 'critical'))
      .map((r) => r.rule_id),
    [rules])

  const toggleRule = (id) => onChange(
    selected.includes(id) ? selected.filter((r) => r !== id) : [...selected, id])

  const label = selected.length === 0
    ? `All rules (${withEvents.length} with activity)`
    : `${selected.length} rule${selected.length === 1 ? '' : 's'}`

  return (
    <div className="app-select rule-select" ref={ref}>
      <div className="app-select-box" onClick={() => setOpen((v) => !v)}>
        {selected.length === 0
          ? <span style={{ color: '#64748B' }}>{label}</span>
          : <span className="chip on">{label}</span>}
        <span style={{ marginLeft: 'auto', color: '#64748B' }}>▾</span>
      </div>
      {open && (
        <div className="app-select-pop rule-pop">
          <input autoFocus type="search" placeholder="Filter rules…" value={q}
            onChange={(e) => setQ(e.target.value)} />
          <div className="rule-actions">
            <button onClick={() => onChange([])}>All</button>
            <button onClick={() => onChange(withEvents)}
              title="Only the rules that actually found something in this case">
              With activity
            </button>
            <button onClick={() => onChange(flagged)} disabled={flagged.length === 0}
              title="Only rules whose findings need analyst review">
              Needs review
            </button>
          </div>
          <div className="app-select-list">
            {groups.map(([cls, items]) => (
              <div key={cls}>
                <div className="rule-group">{CLASS_STYLE[cls].label}</div>
                {items.map((r) => (
                  <label key={r.rule_id}
                    className={'app-opt rule-opt' + (r.event_count === 0 ? ' dim' : '')}
                    title={`${r.how || r.title}${r.note ? `\n\n${r.note}` : ''}`}>
                    <input type="checkbox" checked={selected.includes(r.rule_id)}
                      onChange={() => toggleRule(r.rule_id)} />
                    <span className="app-opt-name">{r.title}</span>
                    {r.status !== 'active' && (
                      <span className={'rule-status ' + r.status}>
                        {r.status === 'degraded' ? 'limited' : 'no data'}
                      </span>
                    )}
                    <span className="app-opt-count">{r.event_count.toLocaleString()}</span>
                  </label>
                ))}
              </div>
            ))}
            {groups.length === 0 && <div className="app-opt-empty">No rules match.</div>}
          </div>
        </div>
      )}
    </div>
  )
}

// Searchable multi-select for the (long) app list. Native, no dependencies.
function AppMultiSelect({ apps, selected, onChange }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef(null)

  useEffect(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const list = needle ? apps.filter((a) => a.app.toLowerCase().includes(needle)) : apps
    return list.slice(0, 200)
  }, [apps, q])

  const toggleApp = (app) => onChange(
    selected.includes(app) ? selected.filter((a) => a !== app) : [...selected, app])

  return (
    <div className="app-select" ref={ref}>
      <div className="app-select-box" onClick={() => setOpen((v) => !v)}>
        {selected.length === 0
          ? <span style={{ color: '#64748B' }}>All apps ({apps.length})</span>
          : selected.map((a) => (
            <span key={a} className="chip on" onClick={(e) => { e.stopPropagation(); toggleApp(a) }}>
              {a} ✕
            </span>
          ))}
        <span style={{ marginLeft: 'auto', color: '#64748B' }}>▾</span>
      </div>
      {open && (
        <div className="app-select-pop">
          <input autoFocus type="search" placeholder="Filter apps…" value={q}
            onChange={(e) => setQ(e.target.value)} />
          <div className="app-select-list">
            {filtered.map((a) => (
              <label key={a.app} className="app-opt">
                <input type="checkbox" checked={selected.includes(a.app)}
                  onChange={() => toggleApp(a.app)} />
                <span className="app-opt-name">{a.app}</span>
                <span className="app-opt-count">{a.event_count}</span>
              </label>
            ))}
            {filtered.length === 0 && <div className="app-opt-empty">No apps match.</div>}
          </div>
        </div>
      )}
    </div>
  )
}
