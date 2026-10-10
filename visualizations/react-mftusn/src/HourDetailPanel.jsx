import React from 'react'
import { flagColor, flagLabel, fmtBytes, fmtDay, fmtInt, baseName } from './format.js'
import { FlagChips, PathCell, sortFlags } from './WindowSection.jsx'

/**
 * Drill-down for a single hour of the selected day.
 *
 * The counts come from the day payload's own `byHour` (counted in SQL over
 * every record of the day). The list is that hour's records, a page at a time:
 * the day payload carries one page of the day, not the day - on a real case one
 * day held 283,585 records - so filtering it client-side, as the other
 * dashboards do, would have shown the hour's share of one page and called it
 * the hour.
 */
export default function HourDetailPanel({ hour, bucket, detail, page, loading, onPage, onOpenFile, onClose }) {
  const hh = String(hour).padStart(2, '0')
  const byHour = detail?.byHour || {}
  const counts = sortFlags(Object.keys(byHour))
    .map(f => [f, (byHour[f] || [])[hour] || 0])
    .filter(([, n]) => n > 0)
  const rows = page?.events || []
  const total = page?.total || 0
  const pageNo = page?.page || 0
  const size = page?.pageSize || 500
  const to = Math.min(total, (pageNo + 1) * size)

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">File activity at {hh}:00</div>
          <div className="detail-sub">
            {fmtDay(String(bucket || '').slice(0, 10))} &middot; {fmtInt(total)} USN record
            {total === 1 ? '' : 's'} in this hour
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">By reason (this hour)</div>
          <div className="prov-list tight">
            {counts.length ? counts.map(([f, n]) => (
              <div className="prov-row" key={f}>
                <span className="prov-name">
                  <span className="prov-swatch" style={{ background: flagColor(f) }} />
                  {flagLabel(f)}
                </span>
                <span className="prov-count">{fmtInt(n)}</span>
              </div>
            )) : <div className="detail-none small">Nothing changed in this hour.</div>}
          </div>
          <div className="ov-hint">
            One record can carry several reasons, so these can add up to more than the
            record count.
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title evt-title">
            <span>Records {total ? `${fmtInt(pageNo * size + 1)}–${fmtInt(to)} of ${fmtInt(total)}` : ''}</span>
            {total > size && (
              <span className="pager">
                <button disabled={pageNo <= 0 || loading} onClick={() => onPage(pageNo - 1)}>Previous</button>
                <button disabled={to >= total || loading} onClick={() => onPage(pageNo + 1)}>Next</button>
              </span>
            )}
          </div>
          {loading && !rows.length ? <div className="loading-inline"><span className="spinner" />Loading…</div> : (
            <div className="hour-table">
              <div className="hour-row hour-head">
                <span>Time</span><span>Reasons</span><span>File</span>
                <span>Path</span><span>Size</span><span />
              </div>
              {rows.map((e, i) => (
                <div className="hour-row hour-row--open" key={i}
                  title="Open file timeline"
                  onClick={() => onOpenFile && onOpenFile(e.id)}>
                  <span>{String(e.t).slice(11, 19) || '—'}</span>
                  <span><FlagChips flags={e.flags} /></span>
                  <span className="hour-app">{e.name || baseName(e.path)}</span>
                  <PathCell e={e} />
                  <span>{e.inMft ? fmtBytes(e.size) : '—'}</span>
                  <span />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
