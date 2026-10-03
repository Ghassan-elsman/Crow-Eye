import React, { useMemo } from 'react'
import { LOC_COLOR, LOC_LABEL, fmtDay, fmtInt, fmtWhen } from './format.js'

/**
 * Drill-down for a single hour of the selected day.
 *
 * Built entirely from the day detail already loaded - every bridge's day
 * payload carries a per-event `hour` alongside the `byHour` histogram it draws
 * the chart from, so the filter is client-side and there is no second round
 * trip. Same approach as react-viz's panel of this name, which says so in its
 * own header.
 *
 * The hour chart used to look interactive and do nothing: four of the six
 * dashboards drew it with react-chartjs-2 but never wired an onClick.
 */
export default function HourDetailPanel({ hour, day, detail, onOpenProgram, onClose }) {
  const hh = String(hour).padStart(2, '0')

  const rows = useMemo(
    () => (detail?.events || []).filter(e => e.hour === hour),
    [detail, hour])

  // The same breakdown the chart is stacked by, counted for this hour alone.
  const byLocation = useMemo(() => {
    const out = {}
    for (const e of rows) out[e.location] = (out[e.location] || 0) + 1
    return out
  }, [rows])

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">Executions at {hh}:00</div>
          <div className="detail-sub">
            {fmtDay(day)} &middot; {rows.length} run{rows.length === 1 ? '' : 's'} in this hour
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">By run location (this hour)</div>
          <div className="prov-list tight">
            {Object.keys(byLocation).length ? Object.entries(byLocation)
              .sort((a, b) => b[1] - a[1])
              .map(([loc, n]) => (
                <div className="prov-row" key={loc}>
                  <span className="prov-name">
                    <span className="prov-swatch" style={{ background: LOC_COLOR[loc] }} />
                    {LOC_LABEL[loc] || loc}
                  </span>
                  <span className="prov-count">{fmtInt(n)}</span>
                </div>
              )) : <div className="detail-none small">Nothing ran in this hour.</div>}
          </div>
        </div>

        {rows.length ? (
          <div className="detail-card">
            <div className="detail-card-title">Programs that ran at {hh}:00</div>
            <div className="hour-table">
              <div className="hour-row hour-head">
                <span>Time</span><span>Program</span><span>Location</span>
                <span>Volume</span><span>Runs</span><span />
              </div>
              {rows.map((e, i) => (
                <div className="hour-row hour-row--open" key={i}
                  title="Open program profile"
                  onClick={() => onOpenProgram && e.filename && onOpenProgram(e.filename)}>
                  <span>{fmtWhen(e.t)}</span>
                  <span className="hour-app" title={e.path}>{e.exe}</span>
                  <span>{LOC_LABEL[e.location] || e.location}</span>
                  <span>{e.volume || '—'}</span>
                  <span>{fmtInt(e.runCount)}</span>
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
