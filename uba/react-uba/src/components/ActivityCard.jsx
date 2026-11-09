import { ActivityIcon, Icon } from './icons.jsx'
import FactBadges from './FactBadges.jsx'
import {
  ACTOR_STYLE, SEVERITY_STYLE, CONFIDENCE_TIER, CONFIDENCE_LABEL,
  activityLabel, isFlagged, displayUser, USER_BASIS_NOTE,
  evidenceSourceLabel, evidenceDetail, operatorLabel, APP_STATE_STYLE, driverOf, DRIVER_STYLE,
} from '../styles/tokens.js'

function timeOf(ts) {
  if (!ts) return '—'
  return ts.slice(11, 16)
}

// The full name history of a renamed file: oldest → … → current.
function RenameChain({ names, flagged }) {
  return (
    <div className="rename-chain" title="Name history (oldest to current)">
      {names.map((n, i) => (
        <span key={i}>
          <span className={'rn-name' + (i === names.length - 1 ? ' current' : '')}
            style={i === names.length - 1 && flagged ? { color: '#ff3b56' } : null}>
            {n}
          </span>
          {i < names.length - 1 && <span className="rn-arrow">→</span>}
        </span>
      ))}
    </div>
  )
}

export default function ActivityCard({ event, isLast, expanded, onToggle, onOpenFull }) {
  const flagged = isFlagged(event)
  const actor = ACTOR_STYLE[event.actor_type] || ACTOR_STYLE['']
  // The actor colour (tokens ACTOR_COLOR): what drove it, when the evidence
  // says; red only for what needs review.
  const driver = driverOf(event)
  const driverColor = driver !== 'unknown' ? DRIVER_STYLE[driver].color : null
  const dotColor = flagged ? '#ff3b56' : (driverColor || actor.color)
  const sev = SEVERITY_STYLE[event.severity] || SEVERITY_STYLE.routine
  const conf = CONFIDENCE_TIER[event.confidence] || { label: event.confidence, color: '#8c95ab' }
  const user = displayUser(event)
  const op = operatorLabel(event)

  return (
    <div className={'tl-row' + (isLast ? ' last' : '')} id={'story-' + event.event_id}>
      <span className="tl-line" />
      <span className="tl-dot" style={{
        background: dotColor,
        boxShadow: flagged ? '0 0 0 4px rgba(255,59,86,0.18)' : 'none',
      }} />
      {/* the time rides the rail, next to its dot, so every time lines up in one column */}
      <span className="tl-railtime">{timeOf(event.ts_start)}</span>

      <div className={'tl-card' + (flagged ? ' flagged' : '') + (driverColor ? ' driven' : '')}
        style={driverColor ? { '--drv': driverColor } : null}
        role="button" tabIndex={0}
        title="Click for proof · double-click for full evidence"
        onClick={() => onToggle(event.event_id)}
        onDoubleClick={() => onOpenFull(event.event_id)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && e.shiftKey) onOpenFull(event.event_id)
          else if (e.key === 'Enter') onToggle(event.event_id)
        }}>
        {/* main row: icon · sentence · right meta cluster (uses the width) */}
        <div className="tl-main">
          <span className="tl-icon">
            <ActivityIcon activity={event.activity} userRule={Boolean(event.user_rule)} size={22} />
          </span>

          <div className="tl-center">
            <p className="tl-text">{event.description}</p>
            <FactBadges details={event.details} />
            {Array.isArray(event.details?.rename_chain) && event.details.rename_chain.length >= 2 && (
              <RenameChain names={event.details.rename_chain} flagged={flagged} />
            )}
            <div className="tl-chips">
              {/* what kind of action, on the left beside the user, where the eye starts */}
              <span className="pill cat">{activityLabel(event.activity)}</span>
              {APP_STATE_STYLE[event.app_state] && (
                <span className="pill operator" style={{ color: APP_STATE_STYLE[event.app_state].color, background: APP_STATE_STYLE[event.app_state].bg }}
                  title={event.app_state_basis || APP_STATE_STYLE[event.app_state].label}>
                  {APP_STATE_STYLE[event.app_state].label}
                </span>
              )}
              {op && (
                <span className="pill operator" style={{ color: op.color, background: op.bg }}
                  title={'Who drove it: ' + (event.operator_basis || op.label)}>
                  {op.label}
                </span>
              )}
              <span className="user-chip"
                title={user.definitive ? 'User named by the evidence' : 'Signed-in user at this time — not proof they performed it'}>
                <Icon name={user.definitive ? 'user' : 'clock'} size={11} strokeWidth={2.4}
                  style={{ verticalAlign: '-1px', marginRight: 4 }} />
                {user.text}{user.basis === 'session' ? ' · logged-in' : ''}
              </span>
              {/* Session context has always been in the payload and rendered
                  nowhere. It is an annotation, never attribution. */}
              {event.session_context && (
                <span className="session-chip"
                  title="Which sign-in session this moment falls inside — context, not proof of who acted">
                  {event.session_context}
                </span>
              )}
              {/* moved off the right edge so every tag sits on the left, in one row */}
              <span className="pill" style={{ color: actor.color, background: actor.bg }}>{actor.label}</span>
              {event.user_rule && (
                <span className="rule-badge" title="Found by a behaviour rule you created">Your rule</span>
              )}
              {flagged && (
                <span className="pill" style={{ color: sev.color, background: sev.bg }}>Needs review</span>
              )}
              {event.aggregate_count > 1 && (
                <span className="count-pill">{event.aggregate_count.toLocaleString()}×</span>
              )}
            </div>
          </div>

          <div className="tl-meta">
            <span className="chevron" style={{ transform: expanded ? 'rotate(180deg)' : 'none' }}>▾</span>
          </div>
        </div>

        {expanded && (
          <div className="tl-proof" onClick={(e) => e.stopPropagation()}>
            <div className="proof-head">
              <span className="proof-title">Forensic proof</span>
              <span className="pill" style={{ color: conf.color, background: `${conf.color}22` }}>
                {conf.label}
              </span>
            </div>
            <ul className="proof-list">
              {(event.evidence || []).map((ref, i) => (
                <li key={i}>
                  <span className="proof-src">{evidenceSourceLabel(ref)}</span>
                  <span className="proof-arrow">→</span>
                  <span className="proof-detail">{evidenceDetail(ref)}</span>
                </li>
              ))}
              {(!event.evidence || event.evidence.length === 0) && (
                <li className="proof-detail">{CONFIDENCE_LABEL[event.confidence] || event.confidence}</li>
              )}
            </ul>
            {event.caveat && <p className="proof-note caveat">⚠ {event.caveat}</p>}
            {flagged && (
              <p className="proof-note flag">This activity was flagged for analyst review ({sev.label.toLowerCase()}).</p>
            )}
            <p className="proof-note">
              <strong>User:</strong> {user.text} — {USER_BASIS_NOTE[user.basis]}
            </p>
            {APP_STATE_STYLE[event.app_state] && event.app_state_basis && (
              <p className="proof-note">
                <strong>{APP_STATE_STYLE[event.app_state].label}:</strong> {event.app_state_basis}
              </p>
            )}
            {op && event.operator_basis && (
              <p className="proof-note">
                <strong>Who drove it:</strong> {op.label} — {event.operator_basis}
              </p>
            )}
            <button className="proof-btn" onClick={() => onOpenFull(event.event_id)}>
              View full evidence →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
