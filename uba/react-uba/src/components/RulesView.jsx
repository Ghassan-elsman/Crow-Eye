import { useCallback, useEffect, useMemo, useState } from 'react'
import { SEVERITY_STYLE } from '../styles/tokens.js'
import { ActivityIcon } from './icons.jsx'

// The on/off switch for every behaviour rule. One saved setting behind both
// screens: this view and Crow-Eye Settings -> User Behavior write the same
// global `uba_disabled_rules`, so a rule turned off here is off in every case.
//
// A switch saves at once. The analysis on screen was built with the old
// switches, so a change offers "Re-run analysis"; until then the Activity
// Story still shows what the old switches found.
//
// "New behaviour rule" opens the Behaviour Rule Creator (a Crow-Eye window,
// through the bridge); your own rules carry the violet "Your rule" icon and an
// Edit button. A rule saved there is listed here at once (refreshKey).

const STATUS_TEXT = {
  active: { label: 'Working', cls: 'active' },
  degraded: { label: 'Limited', cls: 'degraded' },
  unavailable: { label: 'No data', cls: 'unavailable' },
  off: { label: 'Off', cls: 'off' },
}

export default function RulesView({ callBridge, onRerun, refreshKey = 0 }) {
  const [data, setData] = useState(null)
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(null)       // rule id being saved
  const [error, setError] = useState('')

  useEffect(() => {
    callBridge('getRuleSwitches').then((d) => { if (d) setData(d) })
  }, [callBridge, refreshKey])

  const openCreator = useCallback((request) => {
    callBridge('openRuleCreator', JSON.stringify(request || {}))
  }, [callBridge])

  const save = useCallback(async (request, key) => {
    setBusy(key)
    setError('')
    try {
      const d = await callBridge('setRuleEnabled', JSON.stringify(request))
      if (d && d.error) setError(d.error)
      else if (d) {
        setData(d)
        if (d.saved === false) setError('The setting could not be saved - see the application log.')
      }
    } finally {
      setBusy(null)
    }
  }, [callBridge])

  const groups = useMemo(() => {
    if (!data) return []
    const needle = search.trim().toLowerCase()
    const out = []
    const index = {}
    for (const r of data.rules || []) {
      if (needle && !(`${r.title} ${r.rule_id} ${r.activity}`.toLowerCase().includes(needle)))
        continue
      if (!(r.class_label in index)) {
        index[r.class_label] = out.length
        out.push({ label: r.class_label, rows: [] })
      }
      out[index[r.class_label]].rows.push(r)
    }
    return out
  }, [data, search])

  if (!data) return <p style={{ color: 'var(--dim)' }}>Loading…</p>

  const total = (data.rules || []).length
  const off = data.off_count || 0

  return (
    <div className="rules-view">
      <div className="rules-head">
        <button className="rules-btn create" onClick={() => openCreator({})}
          title="Write a behaviour of your own: rows of a parsed table, or a filter over a behaviour found here">
          <ActivityIcon activity="user_rule" userRule size={18} />
          New behaviour rule
        </button>
        {data.user_rule_count > 0 && (
          <span className="rules-mine">
            {data.user_rule_count} rule{data.user_rule_count === 1 ? '' : 's'} of your own
          </span>
        )}
      </div>
      <p className="rules-intro">
        Every behaviour User Behavior looks for, with a switch to stop looking
        for it. A rule that is off is not run in <strong>any</strong> case, and
        its absence is not evidence: the coverage page lists it as
        "Turned off in Settings", never as "nothing found". The same switches
        are in Crow-Eye Settings → User Behavior.
      </p>

      {data.needs_rerun && (
        <div className="rules-rerun">
          <span>
            {data.rules_changed
              ? 'Your rules or the switches changed since this analysis was built. '
              : 'The switches changed since this analysis was built. '}
            The Activity Story still shows what the previous analysis found.
          </span>
          <button className="rules-btn primary" onClick={onRerun}>Re-run analysis</button>
        </div>
      )}

      <div className="rules-toolbar">
        <input type="search" placeholder="Search rules" value={search}
          onChange={(e) => setSearch(e.target.value)} />
        <span className={'rules-count' + (off > 0 ? ' some-off' : '')}>
          {off > 0 ? `${off} of ${total} rules off` : `All ${total} rules on`}
        </span>
        <button className="rules-btn" disabled={off === 0 || busy !== null}
          onClick={() => save({ all_on: true }, '*')}>
          Turn all on
        </button>
      </div>
      {error && <p className="rules-error">{error}</p>}

      {groups.length === 0 && <p className="empty-hint">No rule matches “{search}”.</p>}
      {groups.map((g) => (
        <div className="rules-group" key={g.label}>
          <h3>
            {g.label}
            <span className="rules-group-n">
              {g.rows.filter((r) => r.enabled).length} of {g.rows.length} on
            </span>
          </h3>
          {g.rows.map((r) => {
            const sev = SEVERITY_STYLE[r.severity] || SEVERITY_STYLE.routine
            const st = r.status ? STATUS_TEXT[r.status] : null
            return (
              <div className={'rule-row' + (r.enabled ? '' : ' is-off')} key={r.rule_id}>
                <button
                  className={'switch' + (r.enabled ? ' on' : '')}
                  role="switch" aria-checked={r.enabled}
                  aria-label={(r.enabled ? 'Turn off ' : 'Turn on ') + r.title}
                  disabled={busy !== null}
                  onClick={() => save({ rule_id: r.rule_id, enabled: !r.enabled }, r.rule_id)}>
                  <span className="knob" />
                </button>
                <ActivityIcon activity={r.activity} userRule={r.user_rule} size={22}
                  style={{ flex: 'none', opacity: r.enabled ? 1 : 0.45 }} />
                <div className="rule-main">
                  <div className="rule-title">
                    {r.title}
                    {r.user_rule && <span className="rule-badge">Your rule</span>}
                  </div>
                  <div className="rule-id">{r.rule_id}</div>
                  {r.invalid && r.invalid.length > 0 && (
                    <div className="rule-invalid">Not valid, so not run: {r.invalid.join(' ')}</div>
                  )}
                </div>
                {r.user_rule && (
                  <button className="rules-btn edit" onClick={() => openCreator({ rule_id: r.rule_id })}
                    title="Open this rule in the Behaviour Rule Creator">
                    Edit
                  </button>
                )}
                <span className="pill" style={{ color: sev.color, background: sev.bg }}>
                  {sev.label}
                </span>
                {st && (
                  <span className={'cov-status ' + st.cls}
                    title="Its state in the analysis on screen">{st.label}</span>
                )}
                {r.event_count !== null && r.event_count !== undefined && r.status !== 'off' ? (
                  <span className="count-pill" title="Activities this rule found in the analysis on screen">
                    {r.event_count.toLocaleString()}
                  </span>
                ) : (
                  // An off rule has no count - it was not looked for, which is
                  // not the same as finding nothing. The empty slot keeps the
                  // columns lined up.
                  st && <span className="count-pill placeholder" aria-hidden="true" />
                )}
              </div>
            )
          })}
        </div>
      ))}
    </div>
  )
}
