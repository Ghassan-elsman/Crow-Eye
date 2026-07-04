export default function EmptyState({ status, isDev }) {
  const dbs = status.databases || {}
  const names = Object.keys(dbs)
  return (
    <div className="center-screen">
      <h2>No parsed artifact data found</h2>
      <p>
        User Behavior Analytics reads the forensic artifacts that Crow-Eye
        collects and parses for a case. This case does not have any parsed
        data yet. Parse the computer's artifacts (or import artifact evidence),
        then open this window again.
      </p>
      {isDev && <p>(Running outside the app — no bridge connection.)</p>}
      {names.length > 0 && (
        <div className="db-list">
          {names.map((n) => (
            <span key={n} className={'db-pill ' + (dbs[n].present ? 'present' : 'absent')}>
              {n}{dbs[n].present ? ` · ${dbs[n].total_rows} rows` : ' · missing'}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
