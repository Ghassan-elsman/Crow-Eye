import React, { useMemo } from 'react'
import { SERIES_COLOR, SERIES_LABEL, fmtDay, fmtInt } from './format.js'

/**
 * One hour of the selected day, from the day payload already loaded (every
 * act carries its `hour`); no second bridge call.
 */
export default function HourDetailPanel({ hour, day, detail, onOpenSession, onClose }) {
  const hh = String(hour).padStart(2, '0')
  const rows = useMemo(() => (detail?.events || []).filter(e => e.hour === hour), [detail, hour])
  const bySeries = useMemo(() => {
    const out = {}
    for (const e of rows) out[e.series] = (out[e.series] || 0) + 1
    return out
  }, [rows])
  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">AI agent acts at {hh}:00</div>
          <div className="detail-sub">{fmtDay(day)} &middot; {rows.length} act{rows.length === 1 ? '' : 's'} in this hour</div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>
      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">By act (this hour)</div>
          <div className="prov-list tight">
            {Object.keys(bySeries).length ? Object.entries(bySeries).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
              <div className="prov-row" key={k}>
                <span className="prov-name"><span className="prov-swatch" style={{ background: SERIES_COLOR[k] }} />{SERIES_LABEL[k] || k}</span>
                <span className="prov-count">{fmtInt(n)}</span>
              </div>
            )) : <div className="detail-none small">Nothing in this hour.</div>}
          </div>
        </div>
        {rows.length ? (
          <div className="detail-card">
            <div className="detail-card-title">Acts at {hh}:00</div>
            <div className="hour-table">
              <div className="hour-row hour-head"><span>Time</span><span>Agent</span><span>Act</span><span>Program</span><span>What</span><span /></div>
              {rows.map((e, i) => (
                <div className="hour-row hour-row--open" key={i} title="Open the session" onClick={() => onOpenSession(e.session)}>
                  <span>{String(e.t).slice(11, 19)}</span>
                  <span>{e.agent}</span>
                  <span>{SERIES_LABEL[e.series] || e.kind}</span>
                  <span>{e.program || '—'}</span>
                  <span className="hour-app" title={e.what}>{e.what}</span>
                  <span />
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
