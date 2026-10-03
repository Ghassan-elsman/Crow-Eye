import React from 'react'
import { REASON_COLOR, fmtBytes, fmtFull } from './format.js'
import { IconSearch } from './Icons.jsx'
import FullRecordSection from './FullRecordSection.jsx'

const ROWS = [
  ['created', 'Created'],
  ['modified', 'Modified'],
  ['accessed', 'Accessed'],
  ['mftChanged', 'MFT changed'],
]

export default function FileDetailPanel({ detail, loading, onClose }) {
  if (loading && !detail) return <div className="detail"><div className="loading-inline" style={{ padding: 20 }}><span className="spinner" />Loading file…</div></div>
  if (!detail || detail.rec === undefined) {
    return (
      <div className="detail empty">
        <div className="detail-empty-inner">
          <div className="detail-empty-icon"><IconSearch size={44} /></div>
          Click a file in the events list to see its full timeline — every USN change, and its
          Standard-Info vs File-Name timestamps side by side.
        </div>
      </div>
    )
  }
  const si = detail.si || {}, fn = detail.fnTimes || {}
  const flags = detail.flags || []
  const events = detail.events || []

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">{detail.filename || '(file)'}</div>
          <div className="detail-sub" title={detail.path}>{detail.path} &middot; {detail.isDir ? 'directory' : fmtBytes(detail.size)}{detail.deleted ? ' · deleted' : ''}</div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        {flags.length > 0 && (
          <div className="detail-card flag-card">
            <div className="detail-card-title">Timestamp anomalies</div>
            {flags.map((f, i) => <div className="flag-line" key={i}>&#9888; {f}</div>)}
          </div>
        )}

        <div className="detail-card">
          <div className="detail-card-title">Standard-Info vs File-Name times (timestomping view)</div>
          <div className="mace">
            <div className="mace-row mace-head"><span></span><span>Standard-Info</span><span>File-Name</span></div>
            {ROWS.map(([k, lbl]) => {
              const diff = si[k] && fn[k] && String(si[k]).slice(0, 19) !== String(fn[k]).slice(0, 19)
              return (
                <div className={'mace-row' + (diff ? ' diff' : '')} key={k}>
                  <span className="mace-k">{lbl}</span>
                  <span>{fmtFull(si[k])}</span>
                  <span>{fmtFull(fn[k])}</span>
                </div>
              )
            })}
          </div>
          <div className="ov-hint">Rows where SI and FN differ are highlighted — SI is user-settable (timestomp target), FN is written by the kernel.</div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">USN change timeline ({events.length})</div>
          {events.length ? (
            <div className="life">
              {events.map((e, i) => (
                <div className="life-row" key={i}>
                  <span className="life-dots">
                    {(e.cats || []).map(c => <span key={c} className="cat-dot" style={{ background: REASON_COLOR[c] }} />)}
                  </span>
                  <span className="life-t">{fmtFull(e.t)}</span>
                  <span className="life-r" title={e.reason}>{e.reason}</span>
                </div>
              ))}
            </div>
          ) : <div className="detail-none small">No USN events recorded for this file (MFT record only).</div>}
        </div>
      <FullRecordSection raw={detail?.raw} />
      </div>
    </div>
  )
}
