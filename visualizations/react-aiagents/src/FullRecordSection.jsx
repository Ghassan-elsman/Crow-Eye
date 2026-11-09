import React, { useState } from 'react'

/**
 * The records behind a panel's curated reading.
 *
 * A detail panel shows the fields someone decided were worth reading. Anything
 * the parser stored but the panel never learned about was invisible, and an
 * analyst could not tell "this artifact does not record that" from "this panel
 * does not show it". This closes that gap without making the panel less
 * readable: collapsed by default, every column when opened.
 *
 * Two shapes, because the artifacts are two shapes:
 *
 * - `raw` - **one** source row. A prefetch file, an MFT entry and a shell item
 *   each come from a single row, so the panel shows that row.
 * - `records` - ``{records, total, truncated}`` from `raw_record.source_records`.
 *   An LNK target is reached through LNK_Files, Automatic_JumpLists,
 *   Custom_JumpLists and JLCE at once; a SRUM app spans five providers; a
 *   browser domain spans every table that mentions it. There is no one row to
 *   show, and picking an arbitrary one would be less honest than showing all of
 *   them. The count is stated even when the list is capped.
 *
 * Values the bridge marks `withheld` are listed by name with no value -
 * encrypted passwords, cookie values, saved-card fragments. That a row HAS a
 * stored password is a finding; the password is not, and a raw dump is exactly
 * how one would end up in a report by accident.
 */

function Fields({ fields }) {
  return (
    <div className="fr-list">
      {fields.map((f) => (
        <div className={'fr-row' + (f.withheld ? ' fr-row--withheld' : '')} key={f.name}>
          <span className="fr-name">{f.name}</span>
          <span className="fr-value">
            {f.withheld
              ? 'withheld — stored in the database, not shown here'
              : (f.value === '' ? '—' : f.value)}
          </span>
        </div>
      ))}
    </div>
  )
}

export default function FullRecordSection({ raw, records }) {
  const [open, setOpen] = useState(false)
  const list = records && (records.records || []).length ? records : null
  const one = !list && raw && (raw.fields || []).length ? raw : null
  if (!list && !one) return null

  const withheld = one
    ? one.fields.filter((f) => f.withheld).length
    : list.records.reduce((a, r) => a + r.fields.filter((f) => f.withheld).length, 0)

  const title = one ? 'Full record' : 'Source records'
  const meta = one
    ? `${one.fields.length} columns${one.table ? ` · ${one.table}` : ''}`
    : (list.truncated
      ? `showing ${list.records.length} of ${list.total}`
      : `${list.total} record${list.total === 1 ? '' : 's'}`)

  return (
    <div className="detail-card">
      <div className="fr-head" onClick={() => setOpen(!open)}
        title={one ? 'Every column stored for this record' : 'Every row this record was assembled from'}>
        <span className="detail-card-title">{title}</span>
        <span className="fr-meta">{meta}{withheld ? ` · ${withheld} withheld` : ''}</span>
        <span className="fr-chev">{open ? '−' : '+'}</span>
      </div>
      {open && one ? <Fields fields={one.fields} /> : null}
      {open && list ? (
        <>
          {list.records.map((r, i) => (
            <div className="fr-rec" key={i}>
              <div className="fr-rec-h">{r.label || r.table || `record ${i + 1}`}</div>
              <Fields fields={r.fields} />
            </div>
          ))}
          {list.truncated ? (
            <div className="ov-hint">
              {list.total - list.records.length} more are not listed here. Narrow the
              date range or the search to bring them into view.
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}
