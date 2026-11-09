// A Chart.js tooltip drawn as HTML, so a chart's "sent" / "received" lines can
// carry the same FlowBadge as every other network number (Ghassan,
// 2026-11-04). Chart.js's own tooltip is painted on the canvas and can only
// write text.
//
// `build(tooltip)` returns { title, rows }, each row an HTML string. The box is
// fixed to the page, not the chart, so a chart inside a scroller (the day
// bubble chart) cannot clip it. Its content is replaced only when it changes,
// or every pointer move would restart the badges' arrival animation.
import { flowBadgeHtml } from './FlowBadge.jsx'

export const esc = (s) => String(s == null ? '' : s)
  .replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

/** A plain "label: value" line. */
export const tipLine = (label, value) =>
  `<div class="cj-tip-row"><span class="cj-tip-l">${esc(label)}</span><span class="cj-tip-v">${esc(value)}</span></div>`

/** A line of network badges: tipFlow([['up', '1.2 MB'], ['down', '4 KB']]). */
export const tipFlow = (pairs) =>
  `<div class="cj-tip-row cj-tip-flow">${pairs.map(([dir, v]) => flowBadgeHtml(dir, v)).join('')}</div>`

export function htmlTooltip(build) {
  return ({ chart, tooltip }) => {
    let el = document.getElementById('cj-tip')
    if (!el) {
      el = document.createElement('div')
      el.id = 'cj-tip'
      el.className = 'cj-tip'
      document.body.appendChild(el)
      // Fixed to the page, so it would float in place while its chart scrolls away.
      window.addEventListener('scroll', () => { el.style.opacity = '0' }, true)
    }
    if (!tooltip || tooltip.opacity === 0) { el.style.opacity = '0'; return }
    const built = build(tooltip)
    if (!built) { el.style.opacity = '0'; return }
    const { title, rows } = built
    const html = (title ? `<div class="cj-tip-t">${esc(title)}</div>` : '') + (rows || []).join('')
    if (el.dataset.html !== html) { el.innerHTML = html; el.dataset.html = html }
    // The caret, held inside the plot: an index tooltip averages every series,
    // and one off its axis would otherwise pull the box off the chart.
    const r = chart.canvas.getBoundingClientRect()
    const a = chart.chartArea || { top: 0, bottom: r.height }
    const x = r.left + tooltip.caretX
    const y = r.top + Math.max(a.top, Math.min(tooltip.caretY, a.bottom))
    const w = el.offsetWidth, h = el.offsetHeight
    const left = x + 14 + w > window.innerWidth - 8 ? x - 14 - w : x + 14
    const top = Math.max(8, Math.min(y - h / 2, window.innerHeight - h - 8))
    el.style.left = Math.max(8, left) + 'px'
    el.style.top = top + 'px'
    el.style.opacity = '1'
  }
}
