const STATUS_LABEL = {
  active: 'Working',
  degraded: 'Limited',
  unavailable: 'No data',
  requires_collection: 'By design',
}

export default function CoveragePanel({ coverage, rules, onFocusRule }) {
  if (!coverage) return <p style={{ color: '#8c95ab' }}>Loading…</p>
  const groups = { active: [], degraded: [], unavailable: [] }
  for (const r of coverage.rules) (groups[r.status] || groups.active).push(r)

  // Event counts come from the rule catalogue, which is built over the whole
  // store. A rule that is WORKING and still found nothing is a real finding and
  // this is the only place it is visible.
  const countOf = Object.fromEntries(
    (rules || []).map((r) => [r.rule_id, r.event_count]))
  const foundNothing = groups.active.filter((r) => countOf[r.rule_id] === 0)

  const Section = ({ title, rows, help }) => rows.length === 0 ? null : (
    <div className="coverage-section">
      <h3>{title}</h3>
      {help && <p style={{ color: '#8c95ab', fontSize: 12, marginTop: -4 }}>{help}</p>}
      {rows.map((r) => {
        const n = countOf[r.rule_id]
        return (
          <div className="cov-row" key={r.rule_id}>
            <span className={'cov-status ' + r.status}>{STATUS_LABEL[r.status]}</span>
            <div style={{ flex: 1 }}>
              <div className="cov-title">
                {r.title}
                {n !== undefined && (
                  <span className={'cov-count' + (n === 0 ? ' zero' : '')}
                    title={n === 0
                      ? 'The data this rule reads was available and it found nothing in it'
                      : `${n.toLocaleString()} activities found by this rule`}>
                    {n.toLocaleString()}
                  </span>
                )}
                {n > 0 && onFocusRule && (
                  <button className="cov-only" onClick={() => onFocusRule(r.rule_id)}
                    title="Show only this rule's findings in the Activity Story">
                    Show only this →
                  </button>
                )}
              </div>
              {r.how && <div className="cov-how"><strong>How:</strong> {r.how}</div>}
              {r.artifacts && r.artifacts.length > 0 && (
                <div className="cov-artifacts">
                  <span className="cov-art-label">Artifacts used:</span>
                  {r.artifacts.map((a, i) => <span key={i} className="cov-art-chip">{a}</span>)}
                </div>
              )}
              {r.note && <div className="cov-note">{r.note}</div>}
            </div>
          </div>
        )
      })}
    </div>
  )

  return (
    <div>
      <p style={{ color: '#8c95ab' }}>
        Crow-Eye's User Behavior Analytics is built to work on <strong>any
        default Windows configuration</strong> — it relies only on the forensic
        artifacts every Windows machine keeps, never on optional telemetry
        (like Sysmon) or extra auditing that most computers do not enable. This
        page shows honestly what could and could not be detected for this case,
        so nothing is read as absence of activity when it is really absence of
        the underlying data.
      </p>
      {foundNothing.length > 0 && (
        <p className="cov-nothing">
          <strong>{foundNothing.length}</strong> of the working detections found
          nothing in this case ({foundNothing.map((r) => r.title).join(', ')}).
          The data they read was present — so this is a statement about this
          computer, not about missing evidence.
        </p>
      )}
      <Section title={`Working detections (${groups.active.length})`} rows={groups.active} />
      <Section title={`Limited — shown from disk evidence only (${groups.degraded.length})`}
        rows={groups.degraded}
        help="Windows was not configured to log these, so they are recovered from on-disk artifacts at lower certainty." />
      <Section title={`No data available (${groups.unavailable.length})`} rows={groups.unavailable} />

      {coverage.requires_collection && coverage.requires_collection.length > 0 && (
        <div className="coverage-section">
          <h3>Out of scope by design — needs optional telemetry ({coverage.requires_collection.length})</h3>
          <p style={{ color: '#8c95ab', fontSize: 12, marginTop: -4 }}>
            These behaviors cannot be detected from default Windows artifacts.
            They require optional telemetry (such as Sysmon) or extra auditing
            that most machines do not enable — so Crow-Eye intentionally does
            not depend on them. Absence here is expected, not a failure.
          </p>
          {coverage.requires_collection.map((r, i) => (
            <div className="cov-row" key={i}>
              <span className="cov-status requires_collection">{STATUS_LABEL.requires_collection}</span>
              <div>
                <div className="cov-title">{r.activity}</div>
                <div className="cov-note">Needs: {r.needs}</div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
