import { Icon } from './icons.jsx'
import {
  END_BASIS_STYLE, END_BASIS_NOTE, logonTypeLabel, durationLabel,
} from '../styles/tokens.js'

function timeOf(ts) {
  return ts ? ts.replace(' ', ' · ') : '—'
}

/**
 * Sign-in / sign-out as its own view.
 *
 * In the storyline a sign-in, a sign-out and an unlock are three cards that all
 * read "Session"; here a session is one row that says who, how they signed in,
 * how long it lasted and — when Windows recorded no sign-out — that the duration
 * is simply not known, rather than quietly showing the distance to the end of
 * the log as if it were measured.
 */
export default function SignInsView({ report, onFocusWindow }) {
  if (!report) return <p className="empty-hint">Loading…</p>
  const sessions = report.sessions || []
  const accounts = report.accounts || []
  const uptime = report.uptime || []
  const auditing = report.auditing || {}

  return (
    <div className="signins">
      <p className="si-intro">
        Every interactive sign-in Windows recorded, in order. Service and network
        logons are excluded — they happen constantly in the background and say
        nothing about a person being present. A session with no recorded sign-out
        shows <strong>no duration</strong>: Windows did not record one, and an
        inferred figure would read as a measurement.
      </p>

      {sessions.length === 0 ? (
        <div className="si-empty">
          <p><strong>No interactive sign-in sessions could be reconstructed.</strong></p>
          <p>
            This means the case holds no successful interactive logon records
            (Security 4624, logon type 2, 10 or 11) for a human account — not
            that nobody used the computer. Check <em>What we can see</em> for
            which records were available.
          </p>
        </div>
      ) : (
        <>
          <SessionTiles sessions={sessions} />
          <div className="si-table-wrap">
            <table className="si-table">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>How they signed in</th>
                  <th>Signed in</th>
                  <th>Signed out</th>
                  <th className="num">For</th>
                  <th>How it ended</th>
                  <th className="num">Unlocks</th>
                  <th className="num">Failed first</th>
                  <th className="num">Activity</th>
                  <th aria-label="Show activity" />
                </tr>
              </thead>
              <tbody>
                {sessions.map((s, i) => (
                  <SessionRow key={`${s.start_ts}-${s.username}-${i}`} session={s}
                    onFocusWindow={onFocusWindow} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      <AccountsSection accounts={accounts} />
      <UptimeSection uptime={uptime} />
      <AuditingSection auditing={auditing} sessionCount={sessions.length} />
    </div>
  )
}

function SessionTiles({ sessions }) {
  const open = sessions.filter((s) => s.is_open).length
  const known = sessions.filter((s) => s.duration_seconds !== null)
  const totalKnown = known.reduce((a, s) => a + s.duration_seconds, 0)
  const people = new Set(sessions.map((s) => s.username)).size
  const tiles = [
    { n: sessions.length.toLocaleString(), l: 'Sign-in sessions' },
    { n: people.toLocaleString(), l: people === 1 ? 'Person' : 'People' },
    { n: durationLabel(totalKnown), l: 'Measured time signed in' },
    { n: open.toLocaleString(), l: 'No sign-out recorded',
      color: open ? '#f0a93b' : undefined },
  ]
  return (
    <div className="tiles">
      {tiles.map((t, i) => (
        <div className="tile" key={i}>
          <div className="n" style={t.color ? { color: t.color } : null}>{t.n}</div>
          <div className="l">{t.l}</div>
        </div>
      ))}
    </div>
  )
}

function SessionRow({ session: s, onFocusWindow }) {
  const end = END_BASIS_STYLE[s.end_basis] || END_BASIS_STYLE.open
  const windowEnd = s.end_ts || s.context_end_ts
  return (
    <tr className={s.is_open ? 'si-open' : ''}>
      <td>
        <span className="si-user"><Icon name="logon" size={14} /> {s.username}</span>
      </td>
      <td className="si-dim">{logonTypeLabel(s.logon_type)}</td>
      <td className="si-mono">{timeOf(s.start_ts)}</td>
      <td className="si-mono">
        {s.end_ts ? timeOf(s.end_ts) : <span className="si-unknown">not recorded</span>}
      </td>
      <td className="num si-mono">
        {s.duration_seconds === null
          ? <span className="si-unknown" title={END_BASIS_NOTE.open}>not known</span>
          : durationLabel(s.duration_seconds)}
      </td>
      <td>
        <span className="pill" style={{ color: end.color, background: `${end.color}22` }}
          title={END_BASIS_NOTE[s.end_basis] || ''}>
          {end.label}
        </span>
      </td>
      <td className="num si-mono">{s.unlock_count || 0}</td>
      <td className="num si-mono">
        {s.failed_before
          ? <span style={{ color: '#ff3b56' }}>{s.failed_before}</span>
          : '0'}
      </td>
      <td className="num si-mono">{(s.event_count || 0).toLocaleString()}</td>
      <td>
        {windowEnd && (
          <button className="si-link"
            title={s.is_open
              ? 'Show activity in the window the evidence can place this session in'
              : 'Show everything that happened during this session'}
            onClick={() => onFocusWindow(s.start_ts, windowEnd)}>
            Show →
          </button>
        )}
      </td>
    </tr>
  )
}

function AccountsSection({ accounts }) {
  return (
    <div className="si-section">
      <h3>Accounts on this computer</h3>
      {accounts.length === 0 ? (
        <p className="si-dim">
          No account table was parsed for this case, so per-account sign-in
          history (last sign-in, sign-in count, failed-password count) is not
          available. It comes from the SAM and ProfileList registry hives.
        </p>
      ) : (
        <>
          <p className="si-dim">
            Read from the computer's own account database. This survives a
            Security log that has already rolled over, so it is often the only
            record that an account ever signed in at all.
          </p>
          <div className="si-table-wrap">
            <table className="si-table">
              <thead>
                <tr>
                  <th>Account</th><th>Type</th><th>Enabled</th>
                  <th>Last signed in</th><th className="num">Sign-ins</th>
                  <th className="num">Bad passwords</th><th>Last bad password</th>
                  <th>Profile</th>
                </tr>
              </thead>
              <tbody>
                {accounts.map((a, i) => (
                  <tr key={i}>
                    <td className="si-user">{a.username || '—'}</td>
                    <td className="si-dim">{a.account_type || '—'}</td>
                    <td className="si-dim">
                      {a.account_enabled === null || a.account_enabled === undefined
                        ? '—' : (a.account_enabled ? 'Yes' : 'No')}
                    </td>
                    <td className="si-mono">{a.last_logon || '—'}</td>
                    <td className="num si-mono">
                      {a.login_count === null || a.login_count === undefined
                        ? '—' : a.login_count}
                    </td>
                    <td className="num si-mono">
                      {a.bad_password_count
                        ? <span style={{ color: '#f0a93b' }}>{a.bad_password_count}</span>
                        : (a.bad_password_count === 0 ? '0' : '—')}
                    </td>
                    <td className="si-mono">{a.last_incorrect_password || '—'}</td>
                    <td className="si-dim">{a.has_profile ? 'Yes' : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

function UptimeSection({ uptime }) {
  if (uptime.length === 0) {
    return (
      <div className="si-section">
        <h3>When the computer was on</h3>
        <p className="si-dim">
          No start-up or shutdown records were available for this case.
        </p>
      </div>
    )
  }
  const shown = uptime.slice(-40).reverse()
  return (
    <div className="si-section">
      <h3>When the computer was on ({uptime.length})</h3>
      <p className="si-dim">
        Start-up and shutdown records from the System log. A session can only
        have happened inside one of these windows — an unmatched start-up is
        shown with no end rather than being closed at a guess.
      </p>
      <div className="si-uptime">
        {shown.map((w, i) => (
          <div className="si-up-row" key={i}>
            <Icon name="power" size={13} />
            <span className="si-mono">{w.start_ts}</span>
            <span className="si-arrow">→</span>
            <span className="si-mono">
              {w.end_ts || <span className="si-unknown">no shutdown recorded</span>}
            </span>
          </div>
        ))}
        {uptime.length > shown.length && (
          <p className="si-dim">
            Showing the {shown.length} most recent of {uptime.length}.
          </p>
        )}
      </div>
    </div>
  )
}

function AuditingSection({ auditing, sessionCount }) {
  return (
    <div className="si-section">
      <h3>Was Windows even recording this?</h3>
      {auditing.audit_policy_available && auditing.entries.length > 0 ? (
        <>
          <p className="si-dim">
            The computer's own audit policy, so a short list of sessions can be
            read as "auditing was limited" rather than "nobody signed in".
          </p>
          <div className="si-audit">
            {auditing.entries.map((e, i) => (
              <div className="si-audit-row" key={i}>
                <span className="si-audit-name">{e.name}</span>
                <span className="si-mono si-dim">{e.decoded || '—'}</span>
              </div>
            ))}
          </div>
        </>
      ) : (
        <p className="si-dim">
          The audit policy was not parsed for this case, so it cannot be
          confirmed from the evidence which sign-in events Windows was
          configured to record.
          {sessionCount === 0 && ' Read the empty session list above with that in mind.'}
        </p>
      )}
    </div>
  )
}
