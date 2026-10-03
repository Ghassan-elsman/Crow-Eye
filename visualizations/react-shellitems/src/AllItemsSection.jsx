import React, { useEffect, useState } from 'react'
import { call } from './bridge.js'
import { SOURCE_COLOR, SOURCE_LABEL, TYPE_LABEL, fmtInt } from './format.js'

const PAGE = 500

/**
 * Every shell item that matches the filters, across all days.
 *
 * The rest of the dashboard is read one day at a time - on the reference case
 * that is 42 of 1,178 items on the opening day, and the only way to reach the
 * rest was to click through 125 active days. This is the full list: newest
 * first (or oldest), paged 500 at a time, the same filters as the strip, and a
 * row opens the same item profile as everywhere else.
 */
export default function AllItemsSection({ filterArgs, onOpenItem }) {
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [days, setDays] = useState(0)
  const [order, setOrder] = useState('desc')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  function load(offset, replace) {
    setLoading(true)
    setErr('')
    call('getShellItemsAll', JSON.stringify({ ...filterArgs, order, offset, limit: PAGE }))
      .then((r) => {
        setTotal(r?.total || 0)
        setDays(r?.days || 0)
        setRows((prev) => (replace ? (r?.rows || []) : prev.concat(r?.rows || [])))
      })
      .catch((e) => setErr(String((e && e.message) || e) || 'that query failed'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load(0, true) }, [filterArgs, order])

  return (
    <section className="day-section all-items">
      <div className="detail-card">
        <div className="detail-card-title all-items-head">
          <span>All items ({fmtInt(total)} across {fmtInt(days)} day{days === 1 ? '' : 's'})</span>
          <span className="mode-toggle">
            <button className={order === 'desc' ? 'on' : ''} onClick={() => setOrder('desc')}>NEWEST</button>
            <button className={order === 'asc' ? 'on' : ''} onClick={() => setOrder('asc')}>OLDEST</button>
          </span>
        </div>
        {err && <div className="flag-line">{err}</div>}
        <div className="evt-table">
          <div className="evt-row si-all-row evt-head"><span>Recorded</span><span>Src</span><span>Item</span><span>Path</span><span>User</span></div>
          {rows.map((e) => (
            <div className="evt-row si-all-row" key={e.id} onClick={() => onOpenItem(e.id)} title="Open item profile">
              <span className="evt-t">{e.t ? String(e.t).slice(0, 19) : 'undated'}</span>
              <span><span className="cat-dot" style={{ background: SOURCE_COLOR[e.source] }} title={SOURCE_LABEL[e.source]} /></span>
              <span className="evt-file">{e.target || '—'} <span className="evt-type">{TYPE_LABEL[e.itemType] || ''}</span></span>
              <span className="evt-path" title={e.path}>{e.path || e.volume || ''}</span>
              <span className="evt-path" title={e.user}>{e.user || ''}</span>
            </div>
          ))}
        </div>
        <div className="all-items-foot">
          {loading
            ? <span className="loading-inline"><span className="spinner" />Loading…</span>
            : rows.length < total
              ? <button className="load-more" onClick={() => load(rows.length, false)}>
                  Show {fmtInt(Math.min(PAGE, total - rows.length))} more ({fmtInt(rows.length)} of {fmtInt(total)} shown)
                </button>
              : <span className="ov-hint">All {fmtInt(total)} shown.</span>}
        </div>
      </div>
    </section>
  )
}
