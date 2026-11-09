import { Icon } from './icons.jsx'
import { MEASURE_COLOR } from '../styles/tokens.js'

// The numbers an investigator meets again and again - data sent and received,
// keyboard, mouse and focus time, commands, files, requests, runs - each as a
// small card with its own icon, so the kind of number is seen before it is
// read (Ghassan, 2026-11-03). One neutral "measure" colour (tokens
// MEASURE_COLOR): a measurement is not an actor or a severity; sent and
// received are told apart by the arrow, not by colour.

const KB = 1024
function bytes(n) {
  if (n >= KB ** 3) return (n / KB ** 3).toFixed(1) + ' GB'
  if (n >= KB ** 2) return (n / KB ** 2).toFixed(1) + ' MB'
  if (n >= KB) return (n / KB).toFixed(1) + ' KB'
  return Math.round(n) + ' B'
}
function seconds(s) {
  if (s >= 3600) return (s / 3600).toFixed(1) + ' h'
  if (s >= 60) return Math.round(s / 60) + ' min'
  return Math.round(s) + ' s'
}
const count = (n) => Math.round(n).toLocaleString()

// key in details -> how it reads. The first key present of each row wins.
const FACTS = [
  { keys: ['bytes_sent'], icon: 'arrowUp', label: 'sent', fmt: bytes, raw: 'bytes', flow: 'up' },
  { keys: ['bytes_received'], icon: 'arrowDown', label: 'received', fmt: bytes, raw: 'bytes', flow: 'down' },
  { keys: ['keyboard_s'], icon: 'keyboard', label: 'keyboard', fmt: seconds, raw: 'seconds' },
  { keys: ['mouse_s'], icon: 'mouse', label: 'mouse', fmt: seconds, raw: 'seconds' },
  { keys: ['focus_s'], icon: 'appWindow', label: 'in front', fmt: seconds, raw: 'seconds' },
  { keys: ['watch_seconds'], icon: 'play', label: 'watched', fmt: seconds, raw: 'seconds' },
  { keys: ['prompts'], icon: 'message', label: 'requests', fmt: count },
  { keys: ['command_count', 'commands'], icon: 'terminal', label: 'commands', fmt: count },
  { keys: ['file_count', 'file_changes'], icon: 'file', label: 'files changed', fmt: count },
  { keys: ['sub_agents'], icon: 'run', label: 'sub-agents', fmt: count },
  { keys: ['run_count'], icon: 'run', label: 'runs', fmt: count },
]

export function factsOf(details) {
  const d = details || {}
  const out = []
  for (const f of FACTS) {
    const key = f.keys.find((k) => typeof d[k] === 'number' && !Number.isNaN(d[k]))
    if (key === undefined || d[key] <= 0) continue
    out.push({ ...f, key, value: d[key] })
  }
  return out
}

export default function FactBadges({ details }) {
  const facts = factsOf(details)
  if (!facts.length) return null
  return (
    <div className="facts" style={{ '--measure': MEASURE_COLOR }}>
      {facts.map((f, i) => (
        <span key={f.key} className={'fact' + (f.flow ? ' flow-' + f.flow : '')} style={{ '--i': i }}
          title={`${f.label}: ${f.raw ? Math.round(f.value).toLocaleString() + ' ' + f.raw : f.fmt(f.value)}`}>
          <span className="fact-ico"><Icon name={f.icon} size={13} strokeWidth={2.2} /></span>
          <b>{f.fmt(f.value)}</b>
          <span className="fact-l">{f.label}</span>
        </span>
      ))}
    </div>
  )
}
