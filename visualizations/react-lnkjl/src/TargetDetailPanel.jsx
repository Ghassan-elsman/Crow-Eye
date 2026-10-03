import React from 'react'
import FullRecordSection from './FullRecordSection.jsx'
import { SOURCE_COLOR, SOURCE_LABEL, fmtWhen } from './format.js'
import { IconSearch } from './Icons.jsx'

export default function TargetDetailPanel({ detail, loading, onClose }) {
  if (loading && !detail) return <div className="detail"><div className="loading-inline" style={{ padding: 20 }}><span className="spinner" />Loading target…</div></div>
  if (!detail || detail.target === undefined) {
    return (
      <div className="detail empty">
        <div className="detail-empty-inner">
          <div className="detail-empty-icon"><IconSearch size={44} /></div>
          Click an opened file to see its full profile &mdash; which artifacts recorded it, its
          timestamps, and the volume it lived on.
        </div>
      </div>
    )
  }
  const m = detail.mace || {}, v = detail.volume || {}
  const refs = detail.refs || []

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">{detail.name || '(target)'}</div>
          <div className="detail-sub" title={detail.target}>{detail.target}</div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">Recorded by</div>
          <div className="prov-legend">
            {(detail.sources || []).map(s => (
              <span className="prov-leg" key={s}><span className="prov-swatch" style={{ background: SOURCE_COLOR[s] }} />{SOURCE_LABEL[s]}</span>
            ))}
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Target timestamps &amp; volume</div>
          <div className="mace">
            <div className="mace-row"><span className="mace-k">Accessed</span><span>{fmtWhen(m.accessed)}</span><span></span></div>
            <div className="mace-row"><span className="mace-k">Created</span><span>{fmtWhen(m.created)}</span><span></span></div>
            <div className="mace-row"><span className="mace-k">Modified</span><span>{fmtWhen(m.modified)}</span><span></span></div>
            <div className="mace-row"><span className="mace-k">Volume</span><span>{v.label || '(no label)'} {v.type ? `· ${v.type}` : ''}</span><span>{v.serial || ''}</span></div>
            {detail.mftEntry ? <div className="mace-row"><span className="mace-k">MFT entry</span><span>{detail.mftEntry}</span><span></span></div> : null}
            {detail.tracker ? <div className="mace-row"><span className="mace-k">Tracker MAC</span><span>{detail.tracker}</span><span></span></div> : null}
            {detail.args ? <div className="mace-row"><span className="mace-k">Arguments</span><span>{detail.args}</span><span></span></div> : null}
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">References ({refs.length})</div>
          <div className="life">
            {refs.map((r, i) => (
              <div className="life-row" key={i}>
                <span className="life-dots"><span className="cat-dot" style={{ background: SOURCE_COLOR[r.source] }} /></span>
                <span className="life-t">{fmtWhen(r.tAccess)}</span>
                <span className="life-r" title={r.sourceName}>{r.app ? r.app + ' · ' : ''}{r.sourceName}</span>
              </div>
            ))}
          </div>
        </div>
        <FullRecordSection records={detail?.records} />
      </div>
    </div>
  )
}
