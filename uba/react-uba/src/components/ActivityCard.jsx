import { Icon } from './icons.jsx'
import {
  ACTOR_STYLE, SEVERITY_STYLE, CONFIDENCE_TIER, CONFIDENCE_LABEL,
  activityLabel, isFlagged, displayUser, USER_BASIS_NOTE,
  evidenceSourceLabel, evidenceDetail,
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
  const dotColor = flagged ? '#ff3b56' : actor.color
  const sev = SEVERITY_STYLE[event.severity] || SEVERITY_STYLE.routine
  const conf = CONFIDENCE_TIER[event.confidence] || { label: event.confidence, color: '#8c95ab' }
  const user = displayUser(event)

  return (
    <div className={'tl-row' + (isLast ? ' last' : '')}>
      <span className="tl-line" />
      <span className="tl-dot" style={{
        background: dotColor,
        boxShadow: flagged ? '0 0 0 4px rgba(255,59,86,0.18)' : 'none',
      }} />

      <div className={'tl-card' + (flagged ? ' flagged' : '')}
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
          <span className="tl-icon" style={{ color: flagged ? '#ff3b56' : actor.color }}>
            <Icon name={event.activity} size={19} />
          </span>

          <div className="tl-center">
            <p className="tl-text">{event.description}</p>
            {Array.isArray(event.details?.rename_chain) && event.details.rename_chain.length >= 2 && (
              <RenameChain names={event.details.rename_chain} flagged={flagged} />
            )}
            <span className="user-chip"
              title={user.definitive ? 'User named by the evidence' : 'Signed-in user at this time — not proof they performed it'}>
              {user.definitive ? '👤' : '🕓'} {user.text}{user.basis === 'session' ? ' · logged-in' : ''}
            </span>
          </div>

          <div className="tl-meta">
            <span className="tl-time">{timeOf(event.ts_start)}</span>
            <span className="pill" style={{ color: actor.color, background: actor.bg }}>{actor.label}</span>
            <span className="pill cat">{activityLabel(event.activity)}</span>
            {flagged && (
              <span className="pill" style={{ color: sev.color, background: sev.bg }}>Needs review</span>
            )}
            {event.aggregate_count > 1 && (
              <span className="count-pill">{event.aggregate_count.toLocaleString()}×</span>
            )}
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
            <button className="proof-btn" onClick={() => onOpenFull(event.event_id)}>
              View full evidence →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
