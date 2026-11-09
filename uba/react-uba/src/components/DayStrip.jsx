import { useMemo } from 'react'
import { ActivityIcon } from './icons.jsx'
import { SEVERITY_STYLE } from '../styles/tokens.js'

// One day of the Activity Story on a 00-24 h line: each activity is its icon at
// its time (UTC), stacked when several fall close together. A flagged activity
// is ringed in its severity colour; what the computer did by itself is dimmed.
// Clicking an icon scrolls to its card and opens it (2026-11-03).
const BUCKET_MIN = 20          // activities within 20 minutes share a column
const MAX_STACK = 4            // more than this in one column shows "+N"

function minuteOf(ts) {
  if (!ts || ts.length < 16) return null
  const h = Number(ts.slice(11, 13))
  const m = Number(ts.slice(14, 16))
  return Number.isFinite(h) && Number.isFinite(m) ? h * 60 + m : null
}

export default function DayStrip({ items, onPick, partial }) {
  const columns = useMemo(() => {
    const by = new Map()
    for (const it of items) {
      const minute = minuteOf(it.ts_start)
      if (minute === null) continue
      const key = Math.floor(minute / BUCKET_MIN)
      if (!by.has(key)) by.set(key, [])
      by.get(key).push(it)
    }
    return [...by.entries()].sort((a, b) => a[0] - b[0])
  }, [items])
  // Stretches where keyboard or mouse input was recorded (input activities),
  // drawn behind the icons: activity inside a band had input at that time.
  const bands = useMemo(() => items.filter((it) => it.activity === 'input')
    .map((it) => ({ id: it.event_id, a: minuteOf(it.ts_start), b: minuteOf(it.ts_end || it.ts_start),
      label: it.description }))
    .filter((x) => x.a !== null && x.b !== null && x.b >= x.a), [items])
  if (columns.length === 0) return null
  return (
    <div className="day-strip" aria-label="This day's activity by time">
      <div className="ds-axis">
        {[0, 3, 6, 9, 12, 15, 18, 21, 24].map((h) => (
          <span key={h} style={{ left: `${(h / 24) * 100}%` }}>{String(h).padStart(2, '0')}:00</span>
        ))}
      </div>
      {partial && (
        <div className="ds-note">
          Showing the {items.length} activities loaded so far; load more below to fill the rest of the day.
        </div>
      )}
      <div className="ds-lane">
        {bands.map((band) => (
          <div key={'in' + band.id} className="ds-input"
            style={{ left: `${(band.a / 1440) * 100}%`, width: `${Math.max(0.3, ((band.b - band.a) / 1440) * 100)}%` }}
            title={band.label} />
        ))}
        {columns.map(([key, its]) => (
          <div key={key} className="ds-col"
            style={{ left: `${((key * BUCKET_MIN + BUCKET_MIN / 2) / 1440) * 100}%` }}>
            {its.slice(0, MAX_STACK).map((it) => {
              const id = it.kind === 'group' ? 'g' + it.event_ids[0] : it.event_id
              const sev = SEVERITY_STYLE[it.severity] || SEVERITY_STYLE.routine
              const flagged = it.severity === 'suspicious' || it.severity === 'critical'
                || it.severity === 'notable'
              const computer = it.behavior_class === 'system' || it.behavior_class === 'system_app'
              const label = (it.kind === 'group' ? it.text : it.description) || ''
              return (
                <button key={id} className={'ds-dot' + (computer ? ' ds-computer' : '')}
                  title={`${(it.ts_start || '').slice(11, 16)} UTC - ${label}`}
                  style={flagged ? { boxShadow: `0 0 0 2px ${it.severity === 'critical' ? '#ff3b56' : sev.color}` } : null}
                  onClick={() => onPick(id)}>
                  <ActivityIcon activity={it.activity} userRule={Boolean(it.user_rule)} size={16} />
                  {it.kind === 'group' && <span className="ds-n">{it.count}</span>}
                </button>
              )
            })}
            {its.length > MAX_STACK && (
              <button className="ds-more" title={`${its.length - MAX_STACK} more in this ${BUCKET_MIN} minutes`}
                onClick={() => onPick(its[MAX_STACK].kind === 'group'
                  ? 'g' + its[MAX_STACK].event_ids[0] : its[MAX_STACK].event_id)}>
                +{its.length - MAX_STACK}
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
