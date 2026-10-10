import React, { useEffect, useState } from 'react'
import { latest } from './bridge.js'
import { fmtInt, fmtBytes } from './format.js'
import { FlagChips, PathCell, NOT_IN_MFT } from './WindowSection.jsx'

const PAGE = 500
const KINDS = [['events', 'USN RECORDS'], ['files', 'MFT FILES'], ['renames', 'RENAMES']]

/**
 * Every USN record, MFT file or rename that matches the filters, across all
 * days - the rest of the dashboard is read one day at a time, and on a case
 * whose MFT history spans years that is thousands of clicks. Newest or oldest
 * first, 500 at a time; a row opens the same file timeline as everywhere else.
 */
export default function AllRecordsSection({ filterArgs, onOpenFile }) {
  const [kind, setKind] = useState('events')
  const [order, setOrder] = useState('desc')
  const [rows, setRows] = useState([])
  const [total, setTotal] = useState(0)
  const [available, setAvailable] = useState(true)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  function load(offset, replace) {
    setLoading(true)
    setErr('')
    latest('getMftUsnAll', JSON.stringify({ ...filterArgs, kind, order, offset }))
      .then((r) => {
        setTotal(r?.total || 0)
        setAvailable(r?.available !== false)
        setRows((prev) => (replace ? (r?.rows || []) : prev.concat(r?.rows || [])))
      })
      .catch((e) => setErr(String((e && e.message) || e) || 'that query failed'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { load(0, true) }, [filterArgs, order, kind])

  const noun = kind === 'events' ? 'USN records' : kind === 'files' ? 'MFT files' : 'renames'
  return (
    <section className="day-section all-items">
      <div className="detail-card">
        <div className="detail-card-title all-items-head">
          <span>All {noun} ({fmtInt(total)}) &mdash; every day, the same filters as the strip</span>
          <span className="all-items-ctl">
            <span className="mode-toggle">
              {KINDS.map(([k, l]) => (
                <button key={k} className={kind === k ? 'on' : ''} onClick={() => setKind(k)}>{l}</button>
              ))}
            </span>
            <span className="mode-toggle">
              <button className={order === 'desc' ? 'on' : ''} onClick={() => setOrder('desc')}>NEWEST</button>
              <button className={order === 'asc' ? 'on' : ''} onClick={() => setOrder('asc')}>OLDEST</button>
            </span>
          </span>
        </div>
        {err && <div className="flag-line">{err}</div>}
        {kind === 'renames' && !available && (
          <div className="detail-none small">This case was correlated before renames were recorded &mdash; re-run the MFT/USN correlation to fill them in.</div>
        )}
        <div className="evt-table">
          {kind === 'events' && <>
            <div className="evt-row all-row evt-head"><span>Time</span><span>Reasons</span><span>File</span><span>Path</span><span>Size</span></div>
            {rows.map((e, i) => (
              <div className="evt-row all-row" key={i} onClick={() => onOpenFile(e.id)} title="Open file timeline">
                <span className="evt-t">{String(e.t || '').slice(0, 19)}</span>
                <span><FlagChips flags={e.flags} /></span>
                <span className="evt-file">{e.rename ? `${e.rename.old} → ${e.rename.new}` : (e.name || '(no name)')}
                  {!e.inMft && <span className="evt-gone" title={NOT_IN_MFT}> &middot; not in MFT</span>}</span>
                <PathCell e={e} />
                <span className="evt-size">{e.inMft ? fmtBytes(e.size) : '—'}</span>
              </div>
            ))}
          </>}
          {kind === 'files' && <>
            <div className="evt-row all-row evt-head"><span>Modified (SI)</span><span>Kind</span><span>File</span><span>Path</span><span>Size</span></div>
            {rows.map((f, i) => (
              <div className="evt-row all-row" key={i} onClick={() => onOpenFile(f.id)} title="Open file timeline">
                <span className="evt-t">{String(f.t || '').slice(0, 19) || 'undated'}</span>
                <span className="evt-type">{f.dir ? 'folder' : 'file'}{f.deleted ? ' · deleted' : ''}</span>
                <span className="evt-file">{f.name || '(no name)'}</span>
                <span className="evt-path" title={f.path}>{f.path}</span>
                <span className="evt-size">{f.dir ? '' : fmtBytes(f.size)}</span>
              </div>
            ))}
          </>}
          {kind === 'renames' && <>
            <div className="evt-row all-row evt-head"><span>Renamed</span><span>Moved</span><span>Old name &rarr; new name</span><span>Folder</span><span /></div>
            {rows.map((r, i) => (
              <div className="evt-row all-row" key={i} onClick={() => onOpenFile(r.id)} title="Open file timeline">
                <span className="evt-t">{String(r.t || '').slice(0, 19)}</span>
                <span>{r.move ? <b className="rn-move">moved</b> : ''}</span>
                <span className="evt-file" title={`${r.old} -> ${r.new}`}>{r.old} <span className="rn-arrow">&rarr;</span> {r.new}</span>
                <span className="evt-path" title={r.move ? `${r.oldDir || '?'}\n-> ${r.newDir || '?'}` : r.newDir}>{r.newDir || '(folder unknown)'}</span>
                <span />
              </div>
            ))}
          </>}
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
