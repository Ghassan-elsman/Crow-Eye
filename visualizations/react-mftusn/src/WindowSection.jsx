import React, { useEffect, useState } from 'react'
import { call } from './bridge.js'
import { Chart } from 'react-chartjs-2'
import {
  Chart as ChartJS, CategoryScale, LinearScale, BarElement, BarController, Tooltip,
} from 'chart.js'
import { flagColor, flagLabel, fmtInt, fmtBytes, fmtDay, baseName } from './format.js'
import { IconCalendar } from './Icons.jsx'

ChartJS.register(CategoryScale, LinearScale, BarElement, BarController, Tooltip)

const FLAG_ORDER = ['FILE_CREATE', 'FILE_DELETE', 'RENAME_OLD_NAME', 'RENAME_NEW_NAME',
  'DATA_OVERWRITE', 'DATA_EXTEND', 'DATA_TRUNCATION', 'NAMED_DATA_OVERWRITE', 'NAMED_DATA_EXTEND',
  'NAMED_DATA_TRUNCATION', 'BASIC_INFO_CHANGE', 'SECURITY_CHANGE', 'EA_CHANGE', 'OBJECT_ID_CHANGE',
  'REPARSE_POINT_CHANGE', 'STREAM_CHANGE', 'HARD_LINK_CHANGE', 'INDEXABLE_CHANGE', 'INTEGRITY_CHANGE',
  'COMPRESSION_CHANGE', 'ENCRYPTION_CHANGE', 'TRANSACTED_CHANGE', 'DESIRED_STORAGE_CLASS_CHANGE', 'CLOSE']
export const sortFlags = (flags) => [...flags].sort((a, b) => {
  const ia = FLAG_ORDER.indexOf(a), ib = FLAG_ORDER.indexOf(b)
  return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || (a < b ? -1 : 1)
})

export function FlagChips({ flags }) {
  return (
    <span className="flag-chips">
      {sortFlags(flags || []).map(f => (
        <span key={f} className="flag-chip" title={flagLabel(f)}
          style={{ background: flagColor(f) }} />
      ))}
    </span>
  )
}

export function PathCell({ e }) {
  const from = e.pathFrom === 'journal'
    ? 'Rebuilt from the USN journal: this folder is no longer in the MFT'
    : e.pathFrom === 'mft' ? 'From the MFT' : 'No parent directory left in the MFT or the journal'
  return (
    <span className={'evt-path' + (e.pathFrom === 'journal' ? ' evt-path--journal' : '')}
      title={`${e.path || '(path unknown)'}\n${from}`}>
      {e.path || <i className="evt-nopath">path unknown</i>}
    </span>
  )
}

export default function WindowSection({ bucket, detail, events, loading, eventsLoading,
  onOpenFile, onPickHour, onPage, filterArgs }) {
  if (!bucket) {
    return (
      <section className="day-section empty">
        <div className="day-empty">
          <span className="day-empty-icon"><IconCalendar size={40} /></span>
          Click a day in the strip to see what changed on it &mdash; the files the MFT says were
          created or modified, and every USN record of that day, by hour and by reason.
        </div>
      </section>
    )
  }
  const byHour = detail?.byHour || {}
  const flags = sortFlags(Object.keys(byHour))
  const topDirs = detail?.topDirs || []
  const topExts = detail?.topExts || []
  const mft = detail?.mft || { created: { total: 0, files: [] }, modified: { total: 0, files: [] } }
  const page = events || detail || {}
  const list = page.events || []
  const total = page.total || 0
  const pageNo = page.page || 0
  const size = page.pageSize || 500
  const from = total ? pageNo * size + 1 : 0
  const to = Math.min(total, (pageNo + 1) * size)

  const hourData = {
    labels: Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')),
    datasets: flags.map(f => ({ label: flagLabel(f), backgroundColor: flagColor(f), borderWidth: 0,
      data: byHour[f] || Array(24).fill(0) })),
  }
  const hourOpts = {
    responsive: true, maintainAspectRatio: false, animation: false,
    // The chart looked interactive and did nothing. els[0].index is the hour.
    onClick: (_e, els) => { if (els[0] && onPickHour) onPickHour(els[0].index) },
    onHover: (evt, els) => { if (evt.native) evt.native.target.style.cursor = els.length ? 'pointer' : 'default' },
    plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtInt(c.parsed.y)}` } } },
    scales: {
      x: { stacked: true, ticks: { color: '#94a3b8', font: { size: 11 }, maxRotation: 0, autoSkip: true }, grid: { display: false } },
      y: { stacked: true, ticks: { color: '#94a3b8', font: { size: 11 } }, grid: { color: 'rgba(99,102,241,0.10)' }, beginAtZero: true },
    },
  }

  return (
    <section className="day-section">
      <div className="day-head">
        <div>
          <div className="day-title">Activity on {fmtDay(bucket)}</div>
          <div className="day-sub">
            {fmtInt(mft.created.total)} files created and {fmtInt(mft.modified.total)} modified
            (MFT) &middot; {fmtInt(total)} USN records &mdash; click any file for its full timeline.
          </div>
        </div>
      </div>

      {loading && <div className="loading-inline"><span className="spinner" />Loading the day…</div>}

      <div className="win-grid win-grid--mft">
        <MftList title="Created that day (MFT)" color={flagColor('mft_created')} part={mft.created}
          kind="created" bucket={bucket} filterArgs={filterArgs} onOpenFile={onOpenFile} />
        <MftList title="Modified that day (MFT)" color={flagColor('mft_modified')} part={mft.modified}
          kind="modified" bucket={bucket} filterArgs={filterArgs} onOpenFile={onOpenFile} />
      </div>

      <RenameList part={detail?.renames} bucket={bucket} filterArgs={filterArgs} onOpenFile={onOpenFile} />

      <div className="win-grid">
        <div className="detail-card win-hours">
          <div className="detail-card-title">USN records by hour and reason &mdash; click an hour</div>
          <div className="chart-box tall"><Chart type="bar" data={hourData} options={hourOpts} /></div>
          <div className="flag-legend">
            {flags.map(f => (
              <span className="flag-leg" key={f}>
                <span className="flag-chip" style={{ background: flagColor(f) }} />{flagLabel(f)}
                <b>{fmtInt((detail?.byFlag || {})[f])}</b>
              </span>
            ))}
          </div>
        </div>
        <div className="detail-card">
          <div className="detail-card-title">Top directories (all {fmtInt(total)} records)</div>
          <MiniList rows={topDirs} labelOf={d => d.dir} valueOf={d => d.n}
            noteOf={d => d.fromJournal ? 'rebuilt from the journal' : ''} />
        </div>
        <div className="detail-card">
          <div className="detail-card-title">Top file types</div>
          <MiniList rows={topExts} labelOf={e => e.ext} valueOf={e => e.n} />
        </div>
      </div>

      <div className="detail-card" style={{ marginTop: 14 }}>
        <div className="detail-card-title evt-title">
          <span>USN records {total ? `${fmtInt(from)}–${fmtInt(to)} of ${fmtInt(total)}` : '(none)'}</span>
          {total > size && (
            <span className="pager">
              <button disabled={pageNo <= 0 || eventsLoading} onClick={() => onPage(0)}>First</button>
              <button disabled={pageNo <= 0 || eventsLoading} onClick={() => onPage(pageNo - 1)}>Previous</button>
              <span className="pager-pos">page {fmtInt(pageNo + 1)} of {fmtInt(Math.ceil(total / size))}</span>
              <button disabled={to >= total || eventsLoading} onClick={() => onPage(pageNo + 1)}>Next</button>
              <button disabled={to >= total || eventsLoading} onClick={() => onPage(Math.ceil(total / size) - 1)}>Last</button>
            </span>
          )}
        </div>
        <div className="evt-table">
          <div className="evt-row evt-head"><span>Time</span><span>Reasons</span><span>File</span><span>Path</span><span>Size</span></div>
          {list.map((e, i) => (
            <div className="evt-row" key={i} onClick={() => onOpenFile(e.id)} title="Open file timeline">
              <span className="evt-t">{String(e.t).slice(11, 19)}</span>
              <span><FlagChips flags={e.flags} /></span>
              <span className="evt-file" title={e.rename ? renameTitle(e.rename) : (e.shortName ? `8.3 name: ${e.shortName}` : e.name)}>
                {e.rename
                  ? <><span className={e.rename.side === 'old' ? 'rn-name' : 'rn-name rn-dim'}>{e.rename.old}</span>
                      <span className="rn-arrow">&rarr;</span>
                      <span className={e.rename.side === 'new' ? 'rn-name' : 'rn-name rn-dim'}>{e.rename.new}</span></>
                  : (e.name || baseName(e.path) || '(no name)')}
                {!e.inMft && <span className="evt-gone" title={NOT_IN_MFT}> &middot; not in MFT</span>}
              </span>
              <PathCell e={e} />
              <span className="evt-size">{e.inMft ? fmtBytes(e.size) : '—'}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

export const NOT_IN_MFT = 'Not in the MFT that was read: the file was deleted before collection, or its MFT entry now holds another file. The journal still has its name and its folder.'

const renameTitle = (r) => `Renamed ${r.old} -> ${r.new}` +
  (r.move ? `\nmoved to ${r.newDir || '(folder unknown)'}` : '') +
  `\nthis record is the ${r.side === 'old' ? 'old' : 'new'} name`

// Page through a day list (MFT files, renames) - it stopped at the first 200.
function usePagedPart(part, slot, args) {
  const [cur, setCur] = useState(part)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setCur(part) }, [part])
  const go = (page) => {
    setBusy(true)
    call(slot, JSON.stringify({ ...args, page }))
      .then(setCur).catch(() => {}).finally(() => setBusy(false))
  }
  return [cur, busy, go]
}

function Pager({ part, busy, go, n }) {
  const total = part?.total || 0
  const size = part?.pageSize || 200
  const pageNo = part?.page || 0
  if (total <= size) return null
  const last = Math.ceil(total / size) - 1
  return (
    <span className="pager">
      <button disabled={pageNo <= 0 || busy} onClick={() => go(pageNo - 1)}>Previous</button>
      <span className="pager-pos">{fmtInt(pageNo * size + 1)}&ndash;{fmtInt(Math.min(total, pageNo * size + n))} of {fmtInt(total)}</span>
      <button disabled={pageNo >= last || busy} onClick={() => go(pageNo + 1)}>Next</button>
    </span>
  )
}

function RenameList({ part, bucket, filterArgs, onOpenFile }) {
  const [cur, busy, go] = usePagedPart(part, 'getMftUsnDayRenames', { ...(filterArgs || {}), bucket })
  const rows = cur?.rows || []
  if (!cur || (!rows.length && !cur.total)) return null
  return (
    <div className="detail-card" style={{ marginTop: 14 }}>
      <div className="detail-card-title evt-title">
        <span><span className="usn-sw" style={{ background: flagColor('RENAME_NEW_NAME'), display: 'inline-block', marginRight: 6 }} />
          Renamed that day (old name &rarr; new name, from the journal): {fmtInt(cur.total)}</span>
        <Pager part={cur} busy={busy} go={go} n={rows.length} />
      </div>
      <div className="evt-table rn-table">
        <div className="evt-row rn-row evt-head"><span>Time</span><span>Old name</span><span /><span>New name</span><span>Folder</span></div>
        {rows.map((r, i) => (
          <div className="evt-row rn-row" key={i} onClick={() => onOpenFile(r.id)} title="Open file timeline">
            <span className="evt-t">{String(r.t).slice(11, 19)}</span>
            <span className="rn-name" title={r.old}>{r.old}</span>
            <span className="rn-arrow">&rarr;</span>
            <span className="rn-name" title={r.new}>{r.new}</span>
            <span className="evt-path" title={r.move ? `${r.oldDir || '?'}\n-> ${r.newDir || '?'}` : r.newDir}>
              {r.move ? <><b className="rn-move">moved</b> {r.newDir || '(folder unknown)'}</> : (r.newDir || '(folder unknown)')}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function MftList({ title, color, part: first, kind, bucket, filterArgs, onOpenFile }) {
  const [part, busy, go] = usePagedPart(first, 'getMftUsnDayFiles', { ...(filterArgs || {}), bucket, kind })
  const files = part?.files || []
  return (
    <div className="detail-card">
      <div className="detail-card-title evt-title"><span><span className="usn-sw" style={{ background: color, display: 'inline-block', marginRight: 6 }} />
        {title}: {fmtInt(part?.total)}</span>
        <Pager part={part} busy={busy} go={go} n={files.length} /></div>
      {files.length ? (
        <div className="mft-files">
          {files.map(f => (
            <div className="mft-file" key={f.id} onClick={() => onOpenFile(f.id)} title={f.path || f.name}>
              <span className="mft-t">{String(f.t).slice(11, 19)}</span>
              <span className="mft-name">{f.name}{f.dir ? '/' : ''}</span>
              <span className="mft-path">{f.path}</span>
            </div>
          ))}
        </div>
      ) : <div className="detail-none small">None on this day.</div>}
    </div>
  )
}

function MiniList({ rows, labelOf, valueOf, noteOf }) {
  if (!rows.length) return <div className="detail-none small">No data.</div>
  const max = Math.max(1, ...rows.map(valueOf))
  return (
    <div className="mini-bars">
      {rows.map((r, i) => (
        <div className="mini-bar" key={i} title={`${labelOf(r)} — ${fmtInt(valueOf(r))}${noteOf && noteOf(r) ? ' (' + noteOf(r) + ')' : ''}`}>
          <span className="mini-label">{labelOf(r)}</span>
          <span className="mini-track"><span className="mini-fill" style={{ width: `${(valueOf(r) / max) * 100}%` }} /></span>
          <span className="mini-val">{fmtInt(valueOf(r))}</span>
        </div>
      ))}
    </div>
  )
}
