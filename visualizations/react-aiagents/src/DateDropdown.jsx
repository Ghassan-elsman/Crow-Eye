import React, { useEffect, useMemo, useRef, useState } from 'react'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const WD = ['S', 'M', 'T', 'W', 'T', 'F', 'S']
const pad = (n) => String(n).padStart(2, '0')
const ymd = (y, m, d) => `${y}-${pad(m + 1)}-${pad(d)}`
const daysIn = (y, m) => new Date(y, m + 1, 0).getDate()

function label(range, bounds) {
  if (!range.start) return 'All time'
  if (range.start === bounds.minDate && range.end === bounds.maxDate) return 'All time'
  const f = (s) => { const d = new Date(s + 'T00:00:00'); return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}` }
  return range.start === range.end ? f(range.start) : `${f(range.start)} – ${f(range.end)}`
}

// Every calendar month between min and max (inclusive).
function monthsBetween(minDate, maxDate) {
  const a = new Date(minDate + 'T00:00:00'), b = new Date(maxDate + 'T00:00:00')
  const out = []
  let y = a.getFullYear(), m = a.getMonth()
  while (y < b.getFullYear() || (y === b.getFullYear() && m <= b.getMonth())) {
    out.push({ y, m })
    m += 1; if (m > 11) { m = 0; y += 1 }
  }
  return out
}

export default function DateDropdown({ bounds, activeDays, range, onChange }) {
  const [open, setOpen] = useState(false)
  const startD = new Date((range.start || bounds.minDate) + 'T00:00:00')
  const [sel, setSel] = useState({ y: startD.getFullYear(), m: startD.getMonth() })
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const months = useMemo(() => monthsBetween(bounds.minDate, bounds.maxDate), [bounds.minDate, bounds.maxDate])
  const isAll = !range.start || (range.start === bounds.minDate && range.end === bounds.maxDate)

  function pickAll() { onChange({ start: bounds.minDate, end: bounds.maxDate }); setOpen(false) }
  function pickMonth(y, m) {
    setSel({ y, m })
    const start = ymd(y, m, 1)
    const end = ymd(y, m, daysIn(y, m))
    onChange({ start: start < bounds.minDate ? bounds.minDate : start,
               end: end > bounds.maxDate ? bounds.maxDate : end })
  }
  function pickDay(day) { onChange({ start: day, end: day }); setOpen(false) }

  // build the day grid for the selected month (leading blanks for weekday offset)
  const grid = useMemo(() => {
    const first = new Date(sel.y, sel.m, 1).getDay()
    const total = daysIn(sel.y, sel.m)
    const cells = Array.from({ length: first }, () => null)
    for (let d = 1; d <= total; d++) cells.push(d)
    return cells
  }, [sel])

  return (
    <div className="dd" ref={ref}>
      <button className="dd-btn" onClick={() => setOpen(o => !o)} title="Select date range">
        <span className="dd-cal" aria-hidden="true">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="4.5" width="18" height="16" rx="2" /><path d="M3 9h18M8 2.5v4M16 2.5v4" />
          </svg>
        </span>
        {label(range, bounds)}
        <span className="dd-caret" aria-hidden="true">&#9662;</span>
      </button>

      {open && (
        <div className="dd-panel">
          <button className={'dd-all' + (isAll ? ' on' : '')} onClick={pickAll}>All time</button>
          <div className="dd-months">
            {months.map(({ y, m }) => (
              <button key={`${y}-${m}`}
                className={'dd-month' + (sel.y === y && sel.m === m ? ' on' : '')}
                onClick={() => pickMonth(y, m)}>{MONTHS[m]} {String(y).slice(2)}</button>
            ))}
          </div>
          <div className="dd-wd">{WD.map((w, i) => <span key={i}>{w}</span>)}</div>
          <div className="dd-days">
            {grid.map((d, i) => {
              if (d === null) return <span key={i} className="dd-day blank" />
              const day = ymd(sel.y, sel.m, d)
              const inRange = day >= bounds.minDate && day <= bounds.maxDate
              const has = activeDays.has(day)
              const isSel = range.start === day && range.end === day
              return (
                <button key={i}
                  className={'dd-day' + (has ? ' has' : '') + (isSel ? ' sel' : '')}
                  disabled={!inRange}
                  onClick={() => inRange && pickDay(day)}>{d}</button>
              )
            })}
          </div>
          <div className="dd-hint">Pick a month, then a day &middot; dotted = has activity</div>
        </div>
      )}
    </div>
  )
}
