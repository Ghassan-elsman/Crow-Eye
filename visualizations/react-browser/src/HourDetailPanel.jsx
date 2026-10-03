import React, { useMemo } from 'react'
import { ACTIVITIES, ACTIVITY_COLOR, ACTIVITY_LABEL, fmtDay, fmtInt } from './format.js'

// Drill-down for a single hour of the selected day. Built entirely from data
// already loaded for that day - the hour histogram and the domain-by-hour
// points - so opening an hour costs no bridge call.
//
// The points behind the domain list are the day's top domains only (the bubble
// chart's cap), while the activity counts above them are the real totals for
// the hour. The panel says so rather than letting the two disagree silently.
export default function HourDetailPanel({ hour, day, detail, activity, onPickDomain, onClose }) {
  const hh = String(hour).padStart(2, '0')
  const byActivity = detail?.hourlyBySource || {}

  const total = useMemo(
    () => ACTIVITIES.reduce((s, a) => s + ((byActivity[a.key] || [])[hour] || 0), 0),
    [byActivity, hour])

  const rows = useMemo(() => {
    const agg = {}
    for (const p of (activity?.points || [])) {
      if (p.h !== hour) continue
      const cur = agg[p.domain] || (agg[p.domain] = {
        domain: p.domain, browser: p.browser || '', counts: {}, total: 0,
      })
      cur.counts[p.activity] = (cur.counts[p.activity] || 0) + p.n
      cur.total += p.n
      if (!cur.browser && p.browser) cur.browser = p.browser
    }
    return Object.values(agg).sort((a, b) => b.total - a.total)
  }, [activity, hour])

  const shown = rows.reduce((s, r) => s + r.total, 0)

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">Activity at {hh}:00</div>
          <div className="detail-sub">
            {fmtDay(day)} &middot; {fmtInt(total)} event{total === 1 ? '' : 's'} in this hour
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">Events by activity</div>
          <div className="prov-list tight">
            {ACTIVITIES.map(a => (
              <div className="prov-row" key={a.key}>
                <span className="prov-name">
                  <span className="prov-swatch" style={{ background: a.color }} />
                  {a.label}
                </span>
                <span className="prov-count">{fmtInt((byActivity[a.key] || [])[hour] || 0)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Sites active at {hh}:00</div>
          {rows.length ? (
            <>
              <div className="hour-table">
                <div className="hour-row brh-row hour-head">
                  <span>Site</span><span>Browser</span><span>What happened</span><span>Events</span>
                </div>
                {rows.map(r => (
                  <div className="hour-row brh-row" key={r.domain}
                    onClick={() => onPickDomain && onPickDomain(r.domain)}
                    style={{ cursor: onPickDomain ? 'pointer' : 'default' }}>
                    <span className="hour-app" title={r.domain}>{r.domain}</span>
                    <span className="hour-user" title={r.browser}>{r.browser || '—'}</span>
                    <span className="brh-chips">
                      {ACTIVITIES.filter(a => r.counts[a.key]).map(a => (
                        <span key={a.key} className="evt-chip"
                          style={{ borderColor: ACTIVITY_COLOR[a.key], color: ACTIVITY_COLOR[a.key] }}>
                          {ACTIVITY_LABEL[a.key]} {fmtInt(r.counts[a.key])}
                        </span>
                      ))}
                    </span>
                    <span>{fmtInt(r.total)}</span>
                  </div>
                ))}
              </div>
              {shown < total && (
                <div className="evt-more">
                  {fmtInt(total - shown)} more event{total - shown === 1 ? '' : 's'} this hour
                  belong to sites outside the day&rsquo;s busiest, which the chart above does not plot.
                </div>
              )}
            </>
          ) : (
            <div className="detail-none">
              No site activity plotted for this hour. The hour&rsquo;s events, if any, belong to sites
              outside the day&rsquo;s busiest.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
