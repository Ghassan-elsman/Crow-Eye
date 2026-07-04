import { useEffect, useState } from 'react'
import { ACTOR_STYLE, SEVERITY_STYLE, CONFIDENCE_LABEL, actorLabel, displayUser, USER_BASIS_NOTE } from '../styles/tokens.js'

const ROLE_LABEL = { primary: 'Direct evidence', corroborating: 'Supporting evidence' }

export default function EvidenceModal({ eventId, callBridge, onClose, bridge }) {
  const [data, setData] = useState(null)
  const [offset, setOffset] = useState(0)

  useEffect(() => {
    callBridge('getEvidence', JSON.stringify({ event_id: eventId, offset, page_size: 50 }))
      .then((r) => { if (r && !r.pending) setData(r) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventId, offset])

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const openNative = (group, row) => {
    if (!bridge || !bridge.openEvidenceDetail) return
    bridge.openEvidenceDetail(JSON.stringify({ db: group.db, table: group.table, record: row }))
  }

  const ev = data && data.event
  const actor = ev ? (ACTOR_STYLE[ev.actor_type] || ACTOR_STYLE['']) : null
  const sev = ev ? (SEVERITY_STYLE[ev.severity] || SEVERITY_STYLE.routine) : null

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>×</button>
        <div className="modal-head">
          {ev ? (
            <>
              <h2>{ev.description}</h2>
              <div className="meta" style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                <span className="actor-chip" style={{ color: actor.color, background: actor.bg }}>
                  {actorLabel(ev.actor_type, ev.actor_name)}
                </span>
                <span className="badge" style={{ color: sev.color, background: sev.bg }}>{sev.label}</span>
                <span className="confidence">{CONFIDENCE_LABEL[ev.confidence] || ev.confidence}</span>
              </div>
              {(() => { const u = displayUser(ev); return (
                <div className="basis">
                  <strong>User:</strong> {u.text} — {USER_BASIS_NOTE[u.basis]}
                </div>
              )})()}
              {ev.actor_basis
                ? <div className="basis">Why this actor: {ev.actor_basis}</div>
                : <div className="basis">The evidence itself does not name who performed this (left unattributed on purpose).</div>}
              {ev.session_user && <div className="basis">Signed-in user at this time: {ev.session_user} (association only, not proof of action).</div>}
              {ev.caveat && <div className="basis" style={{ color: '#f0a93b' }}>⚠ {ev.caveat}</div>}
            </>
          ) : <h2>Loading evidence…</h2>}
        </div>
        <div className="modal-body">
          {data && data.groups && data.groups.map((g, gi) => (
            <div className="ev-group" key={gi}>
              <h4>{ROLE_LABEL[g.role] || g.role} — {g.total.toLocaleString()} record{g.total !== 1 ? 's' : ''}</h4>
              <div className="provenance">Source: {g.db} → {g.table}</div>
              {g.error && <div style={{ color: '#ff3b56', fontSize: 12 }}>{g.error}</div>}
              {g.rows && g.rows.length > 0 && <EvidenceTable group={g} onRowOpen={openNative} />}
              {g.has_more && (
                <button className="load-more" onClick={() => setOffset(offset + 50)}>
                  Show more records
                </button>
              )}
            </div>
          ))}
          {data && (!data.groups || data.groups.length === 0) && (
            <p style={{ color: '#8c95ab' }}>No evidence rows available.</p>
          )}
        </div>
      </div>
    </div>
  )
}

function EvidenceTable({ group, onRowOpen }) {
  const rows = group.rows
  const cols = Object.keys(rows[0]).filter((c) => c !== '__rowid__').slice(0, 8)
  return (
    <div className="ev-table-wrap">
      <table className="ev">
        <thead>
          <tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} title="Open the full record" onClick={() => onRowOpen(group, r)}>
              {cols.map((c) => <td key={c}>{formatCell(r[c])}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function formatCell(v) {
  if (v === null || v === undefined) return ''
  const s = String(v)
  return s.length > 80 ? s.slice(0, 80) + '…' : s
}
