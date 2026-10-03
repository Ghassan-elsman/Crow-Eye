import React from 'react'
import FullRecordSection from './FullRecordSection.jsx'
import { fmtInt, fmtBytes, fmtWhen, baseName, dangerLabel, isTypedTransition } from './format.js'

/** Everything the case knows about one domain, across every browser table.
 *
 *  Credentials are shown as metadata only - origin, when, how often. The parser
 *  preserves the ciphertext deliberately and the bridge never returns it, so
 *  there is nothing here to render even if this panel asked.
 */
export default function DomainDetailPanel({ detail, loading, onClose }) {
  // `return null` meant clicking a domain showed nothing at all until the
  // bridge answered - no panel, no spinner, no sign the click registered.
  // Every other dashboard's detail panel guards this way.
  if (loading && !detail) {
    return (
      <div className="detail">
        <div className="loading-inline" style={{ padding: 20 }}>
          <span className="spinner" />Loading domain…
        </div>
      </div>
    )
  }
  if (!detail) return null
  const visits = detail.visits || []
  const cookies = detail.cookies || []
  const cache = detail.cache || []
  const creds = detail.credentials || []
  const downloads = detail.downloads || []

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card wide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{detail.domain}</h3>
          {/* `.detail-close`, not `.modal-x`: nothing styles `.modal-x`, so
              this shipped as a default browser button. */}
          <button className="detail-close" onClick={onClose} title="Close">&times;</button>
        </div>

        <div className="dd-tiles">
          <div className="ov-tile"><div className="ov-tile-v">{fmtInt(detail.visitCount)}</div><div className="ov-tile-l">Visits</div></div>
          <div className="ov-tile"><div className="ov-tile-v">{fmtInt(cookies.length)}</div><div className="ov-tile-l">Cookies</div></div>
          <div className="ov-tile"><div className="ov-tile-v">{fmtInt(cache.length)}</div><div className="ov-tile-l">Cached</div></div>
          <div className="ov-tile"><div className="ov-tile-v">{fmtInt(creds.length)}</div><div className="ov-tile-l">Saved logins</div></div>
          <div className="ov-tile"><div className="ov-tile-v">{fmtInt(downloads.length)}</div><div className="ov-tile-l">Downloads</div></div>
        </div>

        {creds.length ? (
          <div className="dd-sec">
            <div className="dd-h">Saved logins</div>
            <div className="dd-note">Metadata only. Crow-Eye preserves the encrypted blob and never decrypts it, so no secret reaches this panel.</div>
            <table className="dd-table">
              <thead><tr><th>Origin</th><th>Username</th><th>Scheme</th><th>Created</th><th>Last used</th><th>Times</th></tr></thead>
              <tbody>
                {creds.map((c, i) => (
                  <tr key={i}>
                    <td className="mono">{c.origin}</td>
                    <td>{c.hasUsername ? 'stored' : '—'}</td>
                    <td className="mono">{c.scheme || '—'}</td>
                    <td className="mono">{fmtWhen(c.created)}</td>
                    <td className="mono">{fmtWhen(c.lastUsed)}</td>
                    <td>{fmtInt(c.timesUsed)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {downloads.length ? (
          <div className="dd-sec">
            <div className="dd-h">Downloads from this domain</div>
            <table className="dd-table">
              <thead><tr><th>File</th><th>Size</th><th>Started</th><th>Flags</th></tr></thead>
              <tbody>
                {downloads.map((d, i) => (
                  <tr key={i}>
                    <td className="mono" title={d.targetPath}>{baseName(d.targetPath) || '—'}</td>
                    <td>{fmtBytes(d.bytes)}</td>
                    <td className="mono">{fmtWhen(d.started)}</td>
                    <td>
                      {dangerLabel(d.dangerType) ? <span className="ov-flag">flagged</span> : null}
                      {String(d.opened) === '1' ? <span className="ov-opened">opened</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {visits.length ? (
          <div className="dd-sec">
            <div className="dd-h">Visits <span className="dd-count">{fmtInt(detail.visitCount)}</span></div>
            <table className="dd-table">
              <thead><tr><th>When</th><th>Title</th><th>How</th><th>URL</th></tr></thead>
              <tbody>
                {visits.slice(0, 60).map((v, i) => (
                  <tr key={i}>
                    <td className="mono">{fmtWhen(v.time)}</td>
                    <td>{v.title || '—'}</td>
                    <td>
                      {isTypedTransition(v.transition) || v.typed > 0
                        ? <span className="dd-typed">typed</span>
                        : <span className="dd-linked">{v.transition || 'link'}</span>}
                    </td>
                    <td className="mono dd-url" title={v.url}>{v.url}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="dd-sec">
            <div className="dd-h">Visits</div>
            <div className="detail-none small">
              No history row for this domain — yet it appears in the artifacts above.
              That is the anti-forensics signal, not an absence of evidence.
            </div>
          </div>
        )}

        {cookies.length ? (
          <div className="dd-sec">
            <div className="dd-h">Cookies</div>
            <table className="dd-table">
              <thead><tr><th>Name</th><th>Host</th><th>Created</th><th>Last sent</th><th>Expires</th><th>Flags</th></tr></thead>
              <tbody>
                {cookies.slice(0, 40).map((c, i) => (
                  <tr key={i}>
                    <td className="mono">{c.name || '—'}</td>
                    <td className="mono">{c.host}</td>
                    <td className="mono">{fmtWhen(c.created)}</td>
                    <td className="mono">{fmtWhen(c.lastAccess)}</td>
                    <td className="mono">{fmtWhen(c.expires)}</td>
                    <td>
                      {String(c.secure) === '1' ? <span className="dd-chip">secure</span> : null}
                      {String(c.httpOnly) === '1' ? <span className="dd-chip">httpOnly</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {cache.length ? (
          <div className="dd-sec">
            <div className="dd-h">Served from cache</div>
            <table className="dd-table">
              <thead><tr><th>Status</th><th>Type</th><th>Size</th><th>Fetched</th><th>URL</th></tr></thead>
              <tbody>
                {cache.slice(0, 40).map((c, i) => (
                  <tr key={i}>
                    <td className="mono">{c.status || '—'}</td>
                    <td className="mono">{c.contentType || '—'}</td>
                    <td>{c.bytes ? fmtBytes(c.bytes) : '—'}</td>
                    <td className="mono">{fmtWhen(c.fetched)}</td>
                    <td className="mono dd-url" title={c.url}>{c.url}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
        <FullRecordSection records={detail?.records} />
      </div>
    </div>
  )
}
