import React, { useState } from 'react'
import { LOC_COLOR, LOC_LABEL, fmtWhen, fmtInt } from './format.js'
import { IconSearch } from './Icons.jsx'
import FullRecordSection from './FullRecordSection.jsx'

export default function ProgramDetailPanel({ detail, loading, onClose }) {
  const [showAll, setShowAll] = useState(false)
  if (loading && !detail) return <div className="detail"><div className="loading-inline" style={{ padding: 20 }}><span className="spinner" />Loading program…</div></div>
  if (!detail || detail.exe === undefined) {
    return (
      <div className="detail empty">
        <div className="detail-empty-inner">
          <div className="detail-empty-icon"><IconSearch size={44} /></div>
          Click a program to see its full profile &mdash; every run time, where it ran from, and the files
          and DLLs it loaded.
        </div>
      </div>
    )
  }
  const v = detail.volume || {}, pf = detail.pf || {}
  const runs = detail.runTimes || []
  const resources = detail.resources || []
  const shown = showAll ? resources : resources.slice(0, 40)

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">{detail.exe}</div>
          <div className="detail-sub" title={detail.exePath}>
            <span className="cat-dot" style={{ background: LOC_COLOR[detail.location], marginRight: 6 }} />
            {detail.exePath || LOC_LABEL[detail.location]} &middot; ran {fmtInt(detail.runCount)}&times;
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">Run times ({runs.length})</div>
          <div className="life">
            {runs.length ? runs.slice().reverse().map((t, i) => (
              <div className="life-row" key={i}><span className="life-dots"><span className="cat-dot" style={{ background: LOC_COLOR[detail.location] }} /></span><span className="life-t">{fmtWhen(t)}</span><span className="life-r">execution</span></div>
            )) : <div className="detail-none small">No run times.</div>}
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Volume &amp; prefetch file</div>
          <div className="mace">
            <div className="mace-row"><span className="mace-k">Volume</span><span>{v.label || '(no label)'} {v.removable ? '· removable' : ''}</span><span>{v.serial || ''}</span></div>
            <div className="mace-row"><span className="mace-k">.pf created</span><span>{fmtWhen(pf.created)}</span><span></span></div>
            <div className="mace-row"><span className="mace-k">.pf modified</span><span>{fmtWhen(pf.modified)}</span><span></span></div>
            <div className="mace-row"><span className="mace-k">.pf accessed</span><span>{fmtWhen(pf.accessed)}</span><span></span></div>
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Loaded resources ({fmtInt(resources.length)}{detail.unusualCount ? ` · ${fmtInt(detail.unusualCount)} outside System/Program Files` : ''})</div>
          <div className="res-list">
            {shown.map((r, i) => (
              <div className={'res-row' + (r.unusual ? ' unusual' : '')} key={i} title={r.path}>{r.path}</div>
            ))}
          </div>
          {resources.length > 40 && (
            <button className="link" onClick={() => setShowAll(s => !s)}>{showAll ? 'show fewer' : `show all ${resources.length}`}</button>
          )}
          <div className="ov-hint">Highlighted rows loaded from outside System / Program Files &mdash; worth a look for injected or side-loaded modules.</div>
        </div>

        <FullRecordSection raw={detail?.raw} />
      </div>
    </div>
  )
}
