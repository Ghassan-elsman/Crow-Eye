import React, { useMemo } from 'react'
import { SOURCE_COLOR, SOURCE_LABEL, TYPE_LABEL, fmtDay, fmtInt } from './format.js'

/**
 * Drill-down for a single hour of the selected day.
 *
 * Built entirely from the day detail already loaded: every bridge's day payload
 * carries a per-event `hour` alongside the `byHour` histogram the chart is
 * drawn from, so the filter is client-side and there is no second round trip.
 * Same approach as react-viz's panel of this name.
 *
 * The hour chart used to look interactive and do nothing - four of the six
 * dashboards drew it with react-chartjs-2 and never wired an onClick.
 */
export default function HourDetailPanel({ hour, day, detail, onOpenItem, onClose }) {
  const hh = String(hour).padStart(2, '0')

  const rows = useMemo(
    () => (detail?.events || []).filter(e => e.hour === hour),
    [detail, hour])

  // The same breakdown the chart is stacked by, for this hour alone.
  const bySource = useMemo(() => {
    const out = {}
    for (const e of rows) out[e.source] = (out[e.source] || 0) + 1
    return out
  }, [rows])

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">Navigation at {hh}:00</div>
          <div className="detail-sub">
            {fmtDay(day)} &middot; {rows.length} item{rows.length === 1 ? '' : 's'} in this hour
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">By source (this hour)</div>
          <div className="prov-list tight">
            {Object.keys(bySource).length ? Object.entries(bySource)
              .sort((a, b) => b[1] - a[1])
              .map(([src, n]) => (
                <div className="prov-row" key={src}>
                  <span className="prov-name">
                    <span className="prov-swatch" style={{ background: SOURCE_COLOR[src] }} />
                    {SOURCE_LABEL[src] || src}
                  </span>
                  <span className="prov-count">{fmtInt(n)}</span>
                </div>
              )) : <div className="detail-none small">Nothing was browsed in this hour.</div>}
          </div>
        </div>

        {rows.length ? (
          <div className="detail-card">
            <div className="detail-card-title">Places and files at {hh}:00</div>
            <div className="hour-table">
              <div className="hour-row hour-head">
                <span>Time</span><span>Target</span><span>Path</span>
                <span>Volume</span><span>MRU</span><span />
              </div>
              {rows.map((e, i) => (
                <div className="hour-row hour-row--open" key={i}
                  title="Open item profile"
                  onClick={() => onOpenItem && onOpenItem(e.id)}>
                  <span>{String(e.t).slice(11, 19) || '—'}</span>
                  <span className="hour-app">
                    {e.target || '—'}{' '}
                    <span className="evt-type">{TYPE_LABEL[e.itemType] || ''}</span>
                  </span>
                  <span className="hour-app" title={e.path}>{e.path || (e.volume || '—')}</span>
                  <span>{e.volume || '—'}</span>
                  <span>{e.mru !== null && e.mru !== undefined ? '#' + e.mru : '—'}</span>
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
