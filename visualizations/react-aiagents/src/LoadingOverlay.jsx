import React from 'react'

/**
 * Feedback for a RE-load - a filter or date-range change.
 *
 * Every dashboard already had a branded loading screen, but it was a
 * *replacement* gated on the first payload: once data had arrived once, it
 * could never show again. So changing the date range queried the case and gave
 * no sign of it. The inline spinner meant to cover that was dead code - the
 * component returned the full screen on the same condition, so the spinner's
 * `&& !timeline` was never true.
 *
 * This covers `.dash` only, not the header, so the search box, the filters and
 * the date picker stay usable while the reload runs. The Timeline's equivalent
 * is `position: fixed` over everything, which briefly locks the control you
 * are adjusting from.
 *
 * `error` is not the same state as busy: a failed bridge call used to be
 * swallowed by a `.catch()` that substituted empty data, so "the query failed"
 * and "this case has no prefetch data" looked identical on screen.
 */
export default function LoadingOverlay({ show, message, error, brand }) {
  if (!show && !error) return null
  return (
    <div className={'loading-overlay' + (error ? ' loading-overlay--error' : '')}>
      <div className="loading-box">
        {brand ? (
          <div className="loading-brand">
            <span className="brand-mark">{brand[0]}</span>
            <span className="brand-title">{brand[1]}</span>
          </div>
        ) : null}
        {error ? null : (
          <div className="loading-dots" aria-hidden="true"><span /><span /><span /></div>
        )}
        <div className="loading-title">{error || message || 'Working…'}</div>
      </div>
    </div>
  )
}
