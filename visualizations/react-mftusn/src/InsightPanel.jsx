import React from 'react'

/**
 * The records behind an insight.
 *
 * An insight tile used to be a dead number: "19 ran from User / AppData /
 * Temp" with no way to ask which nineteen. The bridges now return
 * `{count, subjects, truncated}` (see visualizations/insights.py), so the tile
 * opens and lists them - and each row opens that dashboard's own detail modal,
 * because a subject carries the id that modal takes.
 *
 * `truncated` is shown rather than hidden: a capped list that looks complete is
 * worse than one that says it is not.
 */
export default function InsightPanel({ title, hint, data, onOpen, onClose }) {
  if (!data) return null
  const subjects = data.subjects || []
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="detail">
          <div className="detail-head">
            <div>
              <div className="detail-title">{title}</div>
              <div className="detail-sub">
                {data.count} {data.count === 1 ? 'record' : 'records'}
                {data.truncated ? ` · showing the first ${subjects.length}` : ''}
              </div>
            </div>
            <button className="detail-close" onClick={onClose} title="Close">&times;</button>
          </div>
          <div className="detail-body">
            {hint ? <div className="ov-hint">{hint}</div> : null}
            {subjects.length ? (
              <div className="detail-card">
                <div className="ins-list">
                  {subjects.map((s, i) => (
                    <div
                      className={'ins-row' + (s.open && onOpen ? ' ins-row--open' : '')}
                      key={`${s.label}-${i}`}
                      title={s.open && onOpen ? 'Open full details' : undefined}
                      onClick={() => s.open && onOpen && onOpen(s.open)}
                    >
                      <span className="ins-label">{s.label}</span>
                      {s.note ? <span className="ins-note">{s.note}</span> : null}
                    </div>
                  ))}
                </div>
                {data.truncated ? (
                  <div className="ov-hint">
                    {data.count - subjects.length} more are not listed here. Narrow the
                    date range or the search to bring them into view.
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="detail-none">
                This insight is a measurement rather than a set of records, so there is
                nothing to open.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
