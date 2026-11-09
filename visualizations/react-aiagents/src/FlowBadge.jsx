import React from 'react'

// Data moving in or out of the machine - network bytes sent and received, a
// file downloaded - shown as the badge the User Behavior window uses for the
// same numbers (uba/react-uba FactBadges.jsx and its `.fact` rules), so it reads
// the same in every dashboard (Ghassan, 2026-11-04).
//
// - An arrow in a rounded square: up = sent / upload, down = received / download.
// - The value in white and a short faint label ("sent" / "received").
// - No hue. The icon is the unit grey #a3a8b3, the card a faint grey. A
//   measurement is not an actor or a severity; sent and received are told apart
//   by the arrow, never by colour. Chart SERIES colours stay what they are.
// - The arrow travels once when the badge appears, and loops while the badge or
//   the row/card around it (class `flow-host`) is under the pointer.
//   prefers-reduced-motion turns the motion off.
//
// The stylesheet travels with the component so the six `styles.css` forks do
// not each grow a copy. Spacing is margins, never flex `gap`: Qt 5.15's
// Chromium 83 ignores `gap` on a flexbox (it arrived in Chromium 84). Duplicated byte-identically in all six dashboards, like
// Icons.jsx (guarded by tests/test_dashboard_css_contracts.py).

const GLYPH = {
  up: '<line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/>',
  down: '<line x1="12" y1="5" x2="12" y2="19"/><polyline points="19 12 12 19 5 12"/>',
}
export const FLOW_LABEL = { up: 'sent', down: 'received' }

const CSS = `
.flowb { display: inline-flex; align-items: center; height: 22px; padding: 0 8px 0 3px;
  border-radius: 6px; border: 1px solid rgba(163, 168, 179, 0.22); background: rgba(163, 168, 179, 0.06);
  font-size: 11.5px; line-height: 1; white-space: nowrap; vertical-align: middle;
  animation: flowb-in .32s ease both; }
.flowb-ico { display: inline-flex; align-items: center; justify-content: center; width: 17px; height: 17px;
  flex-shrink: 0; border-radius: 4px; background: rgba(163, 168, 179, 0.12); color: #a3a8b3; overflow: hidden; }
.flowb .flowb-ico { margin-right: 6px; }
.flowb-v { color: #ffffff; font-weight: 600; font-variant-numeric: tabular-nums;
  font-family: 'JetBrains Mono', 'Space Mono', ui-monospace, monospace; font-size: 11px; }
.flowb-l { color: #7d8597; margin-left: 4px; }
.flowb + .flowb { margin-left: 6px; }
.flowb-ico--lg { width: 24px; height: 24px; border-radius: 6px; margin-right: 10px; }
.flowb-ico--up svg { animation: flowb-up 1.1s ease .2s 1; }
.flowb-ico--down svg { animation: flowb-down 1.1s ease .2s 1; }
.flowb:hover .flowb-ico--up svg, .flow-host:hover .flowb-ico--up svg { animation: flowb-up 1.1s ease infinite; }
.flowb:hover .flowb-ico--down svg, .flow-host:hover .flowb-ico--down svg { animation: flowb-down 1.1s ease infinite; }
@keyframes flowb-in { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
@keyframes flowb-up { 0% { transform: translateY(6px); opacity: 0; } 40% { opacity: 1; } 100% { transform: translateY(-6px); opacity: 0; } }
@keyframes flowb-down { 0% { transform: translateY(-6px); opacity: 0; } 40% { opacity: 1; } 100% { transform: translateY(6px); opacity: 0; } }
@media (prefers-reduced-motion: reduce) {
  .flowb, .flowb-ico svg, .flowb:hover .flowb-ico svg, .flow-host:hover .flowb-ico svg { animation: none !important; }
}
`

if (typeof document !== 'undefined' && !document.getElementById('flowb-css')) {
  const s = document.createElement('style')
  s.id = 'flowb-css'
  s.textContent = CSS
  document.head.appendChild(s)
}

const svgAttrs = (size) => `width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" ` +
  'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"'

/** The arrow in its rounded square, alone - for legends, tiles and headers. */
export function FlowIcon({ dir = 'up', large = false }) {
  const size = large ? 17 : 13
  return (
    <span className={'flowb-ico flowb-ico--' + dir + (large ? ' flowb-ico--lg' : '')}
      dangerouslySetInnerHTML={{ __html: `<svg ${svgAttrs(size)}>${GLYPH[dir]}</svg>` }} />
  )
}

/**
 * The badge. `value` is already formatted; `label` defaults to "sent" /
 * "received" and `label={false}` drops it where a column header names it.
 */
export default function FlowBadge({ dir = 'up', value, label, title }) {
  const l = label === undefined ? FLOW_LABEL[dir] : label
  return (
    <span className="flowb" title={title || (l ? `${l}: ${value}` : undefined)}>
      <FlowIcon dir={dir} />
      <span className="flowb-v">{value}</span>
      {l ? <span className="flowb-l">{l}</span> : null}
    </span>
  )
}

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]))

/** The same badge as an HTML string, for places React does not render (a chart's tooltip). */
export function flowBadgeHtml(dir, value, label) {
  const l = label === undefined ? FLOW_LABEL[dir] : label
  return `<span class="flowb"><span class="flowb-ico flowb-ico--${dir}"><svg ${svgAttrs(13)}>${GLYPH[dir]}</svg></span>` +
    `<span class="flowb-v">${esc(value)}</span>${l ? `<span class="flowb-l">${esc(l)}</span>` : ''}</span>`
}
