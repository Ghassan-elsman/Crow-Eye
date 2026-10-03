import React from 'react'
import { ACTIVITIES, ACTIVITY_COLOR, ACTIVITY_LABEL, fmtInt, fmtBytes, fmtWhen, baseName, dangerLabel } from './format.js'

// An insight is {count, subjects, truncated}; `n` also tolerates the bare
// integer, so a stale bundle degrades to a read-only tile rather than
// rendering "[object Object]".
function n(d) { return (d && typeof d === 'object') ? (d.count || 0) : (d || 0) }

function Anom({ d, l, hot, onOpen }) {
  const can = !!onOpen && (d && typeof d === 'object') && (d.subjects || []).length > 0
  return (
    <div className={'anom' + (hot ? ' hot' : '') + (can ? ' anom--open' : '')}
      title={can ? 'Show the records behind this' : undefined}
      onClick={() => can && onOpen()}>
      <span>{fmtInt(n(d))}</span><label>{l}</label>
    </div>
  )
}

function Tile({ label, value, sub }) {
  return (
    <div className="ov-tile">
      <div className="ov-tile-v">{value}</div>
      <div className="ov-tile-l">{label}</div>
      {sub ? <div className="ov-tile-s">{sub}</div> : null}
    </div>
  )
}

// Generic label/track/value bar list. Borrowed from react-shellitems - it needs
// no Chart.js, so it stays readable at any row count.
function MiniBars({ rows, labelOf, valueOf, colorOf, fmt = fmtInt, onPick }) {
  const max = Math.max(1, ...rows.map(valueOf))
  return (
    <div className="mini-bars">
      {rows.map((r, i) => {
        const v = valueOf(r)
        return (
          <div className={'mb-row' + (onPick ? ' pick' : '')} key={i}
            onClick={onPick ? () => onPick(r) : undefined}>
            <div className="mb-label" title={labelOf(r)}>{labelOf(r)}</div>
            <div className="mb-track">
              <div className="mb-fill" style={{
                width: `${Math.max(2, (v / max) * 100)}%`,
                background: colorOf ? colorOf(r) : 'var(--indigo)',
              }} />
            </div>
            <div className="mb-value">{fmt(v)}</div>
          </div>
        )
      })}
    </div>
  )
}

/** Top domains, with the typed/clicked split drawn as one stacked bar. */
function DomainBars({ rows, onPick }) {
  const max = Math.max(1, ...rows.map(r => r.visits))
  return (
    <div className="mini-bars">
      {rows.map((r) => (
        <div className="mb-row pick" key={r.domain} onClick={() => onPick && onPick(r.domain)}>
          <div className="mb-label" title={r.domain}>{r.domain}</div>
          <div className="mb-track">
            {/* typed first: the part the user chose, rather than passed through */}
            <div className="mb-fill" style={{
              width: `${(r.typed / max) * 100}%`, background: '#39d353',
            }} title={`${fmtInt(r.typed)} typed`} />
            <div className="mb-fill" style={{
              width: `${(r.clicked / max) * 100}%`, background: '#4aa8ff',
            }} title={`${fmtInt(r.clicked)} followed a link`} />
          </div>
          <div className="mb-value">{fmtInt(r.visits)}</div>
        </div>
      ))}
    </div>
  )
}

export default function OverviewPanel({ overview, onPickDomain, onOpenInsight }) {
  if (!overview) return <div className="ov-card"><div className="detail-none small">Loading…</div></div>
  const t = overview.totals || {}
  const src = overview.sourceTotals || {}
  const intent = overview.intent || {}
  const ins = overview.insights || {}
  const downloads = overview.downloads || []

  return (
    <div className="ov-root">
      <div className="ov-tiles">
        <Tile label="Events" value={fmtInt(t.events)} />
        <Tile label="Domains" value={fmtInt(t.domains)} />
        <Tile label="Active days" value={fmtInt(t.activeDays)} />
        <Tile label="Browsers" value={fmtInt(t.browsers)} sub={`${fmtInt(t.profiles)} profiles`} />
      </div>

      <div className="ov-card anomaly-card">
        <div className="ov-card-h">Insights</div>
        <div className="anom-grid">
          <Anom d={ins.historyPruned} l="domains whose history was pruned" hot={n(ins.historyPruned) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('historyPruned')} />
          <Anom d={ins.flaggedDownloads} l="downloads the browser warned about" hot={n(ins.flaggedDownloads) > 0}
            onOpen={() => onOpenInsight && onOpenInsight('flaggedDownloads')} />
          <Anom d={ins.executableDownloads} l="programs and scripts downloaded" hot={false}
            onOpen={() => onOpenInsight && onOpenInsight('executableDownloads')} />
          <Anom d={ins.domains} l="distinct domains" hot={false} />
        </div>
        <div className="ov-hint">
          Cookies, favicons, top sites and sessions outlive a cleared history, so a domain
          carried by two of them with no history row is what a prune leaves behind. Open a
          tile for the records behind it.
        </div>
      </div>

      <div className="ov-card">
        <div className="ov-card-h">Activity mix</div>
        <MiniBars
          rows={ACTIVITIES.filter(a => (src[a.key] || 0) > 0)}
          labelOf={(a) => a.label}
          valueOf={(a) => src[a.key] || 0}
          colorOf={(a) => a.color} />
      </div>

      <div className="ov-card">
        <div className="ov-card-h">Top domains</div>
        <div className="ov-card-note">
          <span className="ov-key"><i style={{ background: '#39d353' }} /> typed</span>
          <span className="ov-key"><i style={{ background: '#4aa8ff' }} /> followed a link</span>
          &middot; a typed address was chosen; a followed link may only have been passed through.
        </div>
        {(overview.topDomains || []).length
          ? <DomainBars rows={overview.topDomains} onPick={onPickDomain} />
          : <div className="detail-none small">No visits in this range.</div>}
      </div>

      <div className="ov-card">
        <div className="ov-card-h">What was typed</div>
        {(intent.terms || []).length ? (
          <>
            <div className="ov-sub">Omnibox terms</div>
            <MiniBars rows={intent.terms} labelOf={(r) => r.text}
              valueOf={(r) => r.hits} onPick={(r) => r.domain && onPickDomain(r.domain)} />
          </>
        ) : null}
        {(intent.typedUrls || []).length ? (
          <>
            <div className="ov-sub">Typed addresses</div>
            <MiniBars rows={intent.typedUrls} labelOf={(r) => r.domain || r.url}
              valueOf={(r) => r.typed} colorOf={() => '#39d353'}
              onPick={(r) => r.domain && onPickDomain(r.domain)} />
          </>
        ) : null}
        {!(intent.terms || []).length && !(intent.typedUrls || []).length
          ? <div className="detail-none small">Nothing typed in this range.</div> : null}
      </div>

      <div className="ov-card">
        <div className="ov-card-h">Downloads</div>
        {downloads.length ? (
          <div className="ov-list">
            {downloads.map((d, i) => (
              <div className="ov-dl" key={i} onClick={() => d.domain && onPickDomain(d.domain)}>
                <div className="ov-dl-top">
                  <span className="ov-dl-name" title={d.targetPath}>{baseName(d.targetPath) || d.sourceUrl}</span>
                  {dangerLabel(d.dangerType) ? <span className="ov-flag">flagged</span> : null}
                  {String(d.opened) === '1' ? <span className="ov-opened">opened</span> : null}
                </div>
                <div className="ov-dl-sub">
                  <span>{d.domain}</span>
                  <span>{fmtBytes(d.bytes)}</span>
                  <span>{fmtWhen(d.started)}</span>
                </div>
              </div>
            ))}
          </div>
        ) : <div className="detail-none small">No downloads in this range.</div>}
      </div>

      <div className="ov-card">
        <div className="ov-card-h">Records by activity</div>
        <div className="prov-list">
          {ACTIVITIES.map(a => (
            <div className="prov-row" key={a.key}>
              <span className="prov-sw" style={{ background: ACTIVITY_COLOR[a.key] }} />
              <span className="prov-name">{ACTIVITY_LABEL[a.key]}</span>
              <span className="prov-n">{fmtInt(src[a.key] || 0)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
