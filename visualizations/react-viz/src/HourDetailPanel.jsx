import React, { useMemo } from 'react'
import { fmtBytes, fmtInt, fmtDuration, fmtDay, PROVIDERS } from './format.js'

// Drill-down for a single hour of the selected day. Built entirely from the
// already-loaded day activity points (no bridge call).
export default function HourDetailPanel({ hour, day, activity, companion, onClose }) {
  const hh = String(hour).padStart(2, '0')

  const rows = useMemo(() => {
    const pts = (activity?.points || []).filter(p => p.h === hour)
    return pts.map(p => ({
      app: p.app, user: p.user,
      sent: p.bytesSent || 0, received: p.bytesReceived || 0,
      cpu: p.cpu || 0, disk: p.disk || 0, focusS: p.focusS || 0,
      total: (p.bytesSent || 0) + (p.bytesReceived || 0),
    })).sort((a, b) => b.total - a.total || b.cpu - a.cpu)
  }, [activity, hour])

  const byProv = companion?.hourlyByProvider || {}

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">Activity at {hh}:00</div>
          <div className="detail-sub">{fmtDay(day)} &middot; {rows.length} record{rows.length === 1 ? '' : 's'} in this hour</div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">Records by provider (this hour)</div>
          <div className="prov-list tight">
            {PROVIDERS.map(p => (
              <div className="prov-row" key={p.key}>
                <span className="prov-name"><span className="prov-swatch" style={{ background: p.color }} />{p.label}</span>
                <span className="prov-count">{fmtInt((byProv[p.key] || [])[hour] || 0)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Applications active at {hh}:00</div>
          {rows.length ? (
            <div className="hour-table">
              <div className="hour-row hour-head">
                <span>App</span><span>User</span><span>&#9650; Sent</span><span>&#9660; Recv</span><span>CPU</span><span>Focus</span>
              </div>
              {rows.map((r, i) => (
                <div className="hour-row" key={i}>
                  <span className="hour-app" title={r.app}>{r.app}</span>
                  <span className="hour-user" title={r.user}>{r.user}</span>
                  <span>{fmtBytes(r.sent)}</span>
                  <span>{fmtBytes(r.received)}</span>
                  <span>{fmtInt(r.cpu)}</span>
                  <span>{fmtDuration(r.focusS)}</span>
                </div>
              ))}
            </div>
          ) : <div className="detail-none">No application activity recorded in this hour.</div>}
        </div>
      </div>
    </div>
  )
}
