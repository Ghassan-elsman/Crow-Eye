import React from 'react'
import FullRecordSection from './FullRecordSection.jsx'
import { SOURCE_COLOR, SOURCE_LABEL, LOC_LABEL, TYPE_LABEL, fmtWhen, fmtBytes } from './format.js'
import { IconSearch } from './Icons.jsx'

export default function ItemDetailPanel({ detail, loading, onClose }) {
  if (loading && !detail) return <div className="detail"><div className="loading-inline" style={{ padding: 20 }}><span className="spinner" />Loading item…</div></div>
  if (!detail || detail.source === undefined) {
    return (
      <div className="detail empty">
        <div className="detail-empty-inner">
          <div className="detail-empty-icon"><IconSearch size={44} /></div>
          Click a shell item to see its full profile &mdash; where it pointed, its MRU order, and every
          timestamp the record carries.
        </div>
      </div>
    )
  }
  const t = detail.times || {}
  const isBag = detail.source === 'shellbags'
  const hasFat = isBag && (t.created || t.modified || t.accessed)

  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <div className="detail-title">{detail.target || '(unnamed)'}</div>
          <div className="detail-sub" title={detail.path}>
            <span className="cat-dot" style={{ background: SOURCE_COLOR[detail.source], marginRight: 6 }} />
            {SOURCE_LABEL[detail.source]} &middot; {TYPE_LABEL[detail.itemType] || 'item'}
            {detail.note ? <span> &middot; {detail.note}</span> : null}
          </div>
        </div>
        <button className="detail-close" onClick={onClose} title="Close">&times;</button>
      </div>

      <div className="detail-body">
        <div className="detail-card">
          <div className="detail-card-title">Where &amp; how</div>
          <div className="mace">
            <div className="mace-row"><span className="mace-k">Full path</span><span style={{ gridColumn: 'span 2', fontFamily: 'var(--mono)' }}>{detail.path || '—'}</span></div>
            <div className="mace-row"><span className="mace-k">Location</span><span>{LOC_LABEL[detail.location] || detail.location}</span><span>{detail.volume || ''}</span></div>
            <div className="mace-row"><span className="mace-k">MRU position</span><span>{detail.mruPosition !== null && detail.mruPosition !== undefined ? '#' + detail.mruPosition : '—'}</span><span>{detail.user ? 'user: ' + detail.user : ''}</span></div>
          </div>
        </div>

        <div className="detail-card">
          <div className="detail-card-title">Timestamps{isBag ? ' — embedded FAT vs registry write' : ''}</div>
          <div className="mace">
            {hasFat && <>
              <div className="mace-row"><span className="mace-k">FAT created</span><span>{fmtWhen(t.created)}</span><span></span></div>
              <div className={'mace-row' + (detail.macMismatch ? ' diff' : '')}><span className="mace-k">{isBag ? 'Folder modified (FAT, from the item)' : 'FAT modified'}</span><span>{fmtWhen(t.modified)}</span><span></span></div>
              <div className="mace-row"><span className="mace-k">FAT accessed</span><span>{fmtWhen(t.accessed)}</span><span></span></div>
            </>}
            <div className={'mace-row' + (detail.macMismatch ? ' diff' : '')}><span className="mace-k">{isBag ? 'Recorded by Explorer (dates this item)' : 'Key last write'}</span><span>{fmtWhen(t.lastWritten || t.keyLastWrite)}</span><span></span></div>
          </div>
          {detail.macMismatch
            ? <div className="flag-line">Embedded folder time and the registry write time fall on different days &mdash; the bag may predate this hive, or a time was altered.</div>
            : <div className="ov-hint">{isBag ? 'A shellbag embeds the folder’s own FAT times. The dashboard dates it by the registry write - when Explorer last recorded the folder - because the FAT times belong to the folder, not to the visit.' : 'This artifact records only the registry key write time — the moment its most-recent entry was written.'}</div>}
        </div>

        {isBag && (
          <div className="detail-card">
            <div className="detail-card-title">Shellbag record</div>
            <div className="mace">
              <div className="mace-row"><span className="mace-k">MFT record</span><span>{detail.mftRecord || '—'}</span><span></span></div>
              <div className="mace-row"><span className="mace-k">Size</span><span>{detail.size ? fmtBytes(detail.size) : '—'}</span><span></span></div>
              <div className="mace-row"><span className="mace-k">Registry path</span><span style={{ gridColumn: 'span 2', fontFamily: 'var(--mono)', whiteSpace: 'normal', wordBreak: 'break-all' }}>{detail.registryPath || '—'}</span></div>
            </div>
          </div>
        )}
        <FullRecordSection raw={detail?.raw} />
      </div>
    </div>
  )
}
