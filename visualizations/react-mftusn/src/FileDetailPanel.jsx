import React from 'react'
import { fmtBytes, fmtFull } from './format.js'
import { IconSearch } from './Icons.jsx'
import FullRecordSection from './FullRecordSection.jsx'
import { FlagChips } from './WindowSection.jsx'

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
  const names = detail.names || []
  const where = detail.pathFrom === 'journal'
    ? 'folder rebuilt from the USN journal - it is no longer in the MFT'
    : detail.pathFrom === 'mft' ? '' : 'folder unknown'

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">{detail.filename || '(file)'}</div>
          <div className="detail-sub" title={detail.path}>
            {detail.volume ? `${detail.volume}:/` : ''}{detail.path || '(path unknown)'} &middot; {detail.isDir ? 'directory' : (detail.inMft ? fmtBytes(detail.size) : 'size unknown')}{detail.deleted ? ' · deleted' : ''}
          </div>
          <div className="detail-sub detail-ids">
            MFT record {detail.rec}{detail.seq != null ? `, sequence ${detail.seq}` : ''}
            {detail.shortName ? ` · 8.3 name ${detail.shortName}` : ''}
            {where ? ` · ${where}` : ''}
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        {!detail.inMft && (
          <div className="detail-card flag-card">
            <div className="detail-card-title">Not in the MFT that was read</div>
            <div className="flag-line">MFT record {detail.rec} (sequence {detail.seq ?? '?'}) was not found
              holding this file when the MFT was read: the file was deleted before collection, or the entry
              now holds another file. What is left of it is the USN journal: its name, its folder and the
              changes below. Its timestamps and size are not recoverable from the MFT.</div>
          </div>
        )}
        {flags.length > 0 && (
          <div className="detail-card flag-card">
            <div className="detail-card-title">Timestamp anomalies</div>
            {flags.map((f, i) => <div className="flag-line" key={i}>&#9888; {f}</div>)}
          </div>
        )}

        {(detail.renames || []).length > 0 && (
          <div className="detail-card">
            <div className="detail-card-title">Renames ({detail.renames.length}) &mdash; old name &rarr; new name, from the journal</div>
            <div className="life">
              {detail.renames.map((r, i) => (
                <div className="life-row rn-life" key={i}>
                  <span className="life-t">{fmtFull(r.t)}</span>
                  <span className="life-r" title={r.move ? `${r.oldDir || '?'}\n-> ${r.newDir || '?'}` : r.newDir}>
                    {r.old} <span className="rn-arrow">&rarr;</span> {r.new}
                    {r.move ? <span className="rn-movenote"> &middot; moved from {r.oldDir || '?'} to {r.newDir || '?'}</span> : null}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {names.length > 1 && (detail.renames || []).length === 0 && (
          <div className="detail-card">
            <div className="detail-card-title">Names recorded for this file ({names.length})</div>
            <div className="name-list">{names.map(n => <span className="name-chip" key={n}>{n}</span>)}</div>
          </div>
        )}

        {detail.inMft && (
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
        )}

        <div className="detail-card">
          <div className="detail-card-title">USN change timeline ({detail.eventsTotal > events.length ? `first ${events.length.toLocaleString()} of ${detail.eventsTotal.toLocaleString()}` : events.length})</div>
          {events.length ? (
            <div className="life">
              {events.map((e, i) => (
                <div className="life-row" key={i}>
                  <span className="life-dots"><FlagChips flags={e.flags} /></span>
                  <span className="life-t">{fmtFull(e.t)}</span>
                  <span className="life-r" title={e.reason}>{e.reason}{e.name && e.name !== detail.filename ? `  (as ${e.name})` : ''}</span>
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
