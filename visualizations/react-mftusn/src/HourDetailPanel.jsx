import React, { useMemo } from 'react'
import { REASON_COLOR, REASON_LABEL, baseName, fmtBytes, fmtDay, fmtInt } from './format.js'

/**
 * Drill-down for a single hour of the selected day.
 *
 * Built entirely from the window detail already loaded: the payload carries a
 * per-event `hour` alongside the `byHour` histogram the chart is drawn from, so
 * the filter is client-side and there is no second round trip. Same approach as
 * react-viz's panel of this name.
 *
 * `bucket` is the selected day. The USN strip used to narrow its cells to hours
 * when the journal window was short, which made this panel degenerate - one
 * populated slot showing the whole cell. A cell is one day on every strip now,
 * so an hour here is always an hour of that day.
 */
export default function HourDetailPanel({ hour, bucket, detail, onOpenFile, onClose }) {
  const hh = String(hour).padStart(2, '0')

  const rows = useMemo(
    () => (detail?.events || []).filter(e => e.hour === hour),
    [detail, hour])

  // The same breakdown the chart is stacked by, for this hour alone. One event
  // can carry several USN reasons, so these counts legitimately exceed the row
  // count - a file created and then written is both.
  const byReason = useMemo(() => {
    const out = {}
    for (const e of rows) for (const c of (e.cats || [])) out[c] = (out[c] || 0) + 1
    return out
  }, [rows])

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">File activity at {hh}:00</div>
          <div className="detail-sub">
            {fmtDay(String(bucket || '').slice(0, 10))} &middot; {rows.length} event
            {rows.length === 1 ? '' : 's'} in this hour
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">By change type (this hour)</div>
          <div className="prov-list tight">
            {Object.keys(byReason).length ? Object.entries(byReason)
              .sort((a, b) => b[1] - a[1])
              .map(([cat, n]) => (
                <div className="prov-row" key={cat}>
                  <span className="prov-name">
                    <span className="prov-swatch" style={{ background: REASON_COLOR[cat] }} />
                    {REASON_LABEL[cat] || cat}
                  </span>
                  <span className="prov-count">{fmtInt(n)}</span>
                </div>
              )) : <div className="detail-none small">Nothing changed in this hour.</div>}
          </div>
          <div className="ov-hint">
            One event can carry several reasons, so these can add up to more than the
            event count.
          </div>
        </div>

        {rows.length ? (
          <div className="detail-card">
            <div className="detail-card-title">Files touched at {hh}:00</div>
            <div className="hour-table">
              <div className="hour-row hour-head">
                <span>Time</span><span>Change</span><span>File</span>
                <span>Path</span><span>Size</span><span />
              </div>
              {rows.map((e, i) => (
                <div className="hour-row hour-row--open" key={i}
                  title="Open file timeline"
                  onClick={() => onOpenFile && onOpenFile(e.rec)}>
                  <span>{String(e.t).slice(11, 19) || '—'}</span>
                  <span className="cat-dots">
                    {(e.cats || []).map(c => (
                      <span key={c} className="cat-dot"
                        style={{ background: REASON_COLOR[c] }} title={c} />
                    ))}
                  </span>
                  <span className="hour-app">{e.fn || baseName(e.path)}</span>
                  <span className="hour-app" title={e.path}>{e.path}</span>
                  <span>{fmtBytes(e.size)}</span>
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
