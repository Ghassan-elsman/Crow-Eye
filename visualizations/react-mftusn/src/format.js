// Display formatters. Values are stored raw; formatting lives only here.

export function fmtInt(n) {
  return (n || 0).toLocaleString()
}

export function fmtBytes(n) {
  n = n || 0
  if (n < 1024) return `${n} B`
  const u = ['KB', 'MB', 'GB', 'TB', 'PB']
  let i = -1
  do { n /= 1024; i++ } while (n >= 1024 && i < u.length - 1)
  return `${n.toFixed(n < 10 ? 2 : 1)} ${u[i]}`
}

export function fmtDuration(sec) {
  sec = Math.round(sec || 0)
  if (sec <= 0) return '0s'
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60
  if (h) return `${h}h ${m}m`
  if (m) return `${m}m ${s}s`
  return `${s}s`
}

export function fmtDay(day) {
  // Accepts 'YYYY-MM-DD' or an hour bucket 'YYYY-MM-DDTHH:00' - use the date part.
  try {
    const d = String(day || '').slice(0, 10)
    return new Date(d + 'T00:00:00').toLocaleDateString(undefined,
      { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })
  } catch { return day }
}

// The five SRUM providers, in display order, with the colour language used
// across every chart in the dashboard.
export const PROVIDERS = [
  { key: 'application_usage', label: 'App Resource', color: '#39d353' },
  { key: 'network_data', label: 'Network Data', color: '#4aa8ff' },
  { key: 'network_connectivity', label: 'Net Conn.', color: '#22d3ee' },
  { key: 'energy', label: 'Energy', color: '#fbbf24' },
  { key: 'app_timeline', label: 'App Timeline', color: '#a78bfa' },
]
export const PROVIDER_COLOR = Object.fromEntries(PROVIDERS.map(p => [p.key, p.color]))
export const PROVIDER_LABEL = Object.fromEntries(PROVIDERS.map(p => [p.key, p.label]))

// 5-step ramp per provider (empty -> full) for its heat-map.
export const PROVIDER_RAMPS = {
  application_usage: ['#151a22', '#0e4429', '#116b34', '#20a34a', '#39d353'],
  network_data: ['#151a22', '#0b3b63', '#125089', '#2a7fd4', '#4aa8ff'],
  network_connectivity: ['#151a22', '#0b4a52', '#0e6b78', '#18a0b0', '#22d3ee'],
  energy: ['#151a22', '#5a3a12', '#8a5a1a', '#c08a1f', '#fbbf24'],
  app_timeline: ['#151a22', '#3a1d63', '#5a2f8f', '#7d4fc0', '#a78bfa'],
}

// ===== MFT/USN dashboard colour language: USN reason = category = colour =====
export const REASONS = [
  { key: 'create', label: 'Create', color: '#39d353', desc: 'FILE_CREATE' },
  { key: 'delete', label: 'Delete', color: '#f43f5e', desc: 'FILE_DELETE' },
  { key: 'rename', label: 'Rename', color: '#fbbf24', desc: 'RENAME_OLD/NEW_NAME' },
  { key: 'data', label: 'Data change', color: '#4aa8ff', desc: 'DATA_OVERWRITE / EXTEND / TRUNCATION' },
  { key: 'meta', label: 'Metadata / Security', color: '#a78bfa', desc: 'BASIC_INFO / SECURITY / OBJECT_ID …' },
]
export const REASON_COLOR = Object.fromEntries(REASONS.map(r => [r.key, r.color]))
export const REASON_LABEL = Object.fromEntries(REASONS.map(r => [r.key, r.label]))
export const REASON_RAMPS = {
  create: ['#0f1626', '#0e4429', '#116b34', '#20a34a', '#39d353'],
  delete: ['#0f1626', '#5c1526', '#8f1d34', '#c62c48', '#f43f5e'],
  rename: ['#0f1626', '#5a3a12', '#8a5a1a', '#c08a1f', '#fbbf24'],
  data: ['#0f1626', '#0b3b63', '#125089', '#2a7fd4', '#4aa8ff'],
  meta: ['#0f1626', '#3a1d63', '#5a2f8f', '#7d4fc0', '#a78bfa'],
}
// MFT-history strip: created vs modified (distinct from the reason palette)
export const MFT_CREATED = '#22d3ee'
export const MFT_MODIFIED = '#6366f1'
export const MFT_RAMPS = {
  created: ['#0f1626', '#0b4a52', '#0e6b78', '#18a0b0', '#22d3ee'],
  modified: ['#0f1626', '#26306b', '#39429c', '#4f5ad0', '#6366f1'],
}

// ===== One colour per USN reason FLAG (the strip has a row per flag) =====
// Each family keeps its category's hue - creates green, deletes red, renames
// amber, data blue, metadata violet - so a flag still reads as its kind of
// change, while no two flags share a colour.
export const FLAG_COLOR = {
  FILE_CREATE: '#39d353',
  FILE_DELETE: '#f43f5e',
  RENAME_OLD_NAME: '#f59e0b',
  RENAME_NEW_NAME: '#fde047',
  DATA_OVERWRITE: '#4aa8ff',
  DATA_EXTEND: '#38bdf8',
  DATA_TRUNCATION: '#818cf8',
  NAMED_DATA_OVERWRITE: '#60a5fa',
  NAMED_DATA_EXTEND: '#7dd3fc',
  NAMED_DATA_TRUNCATION: '#a5b4fc',
  BASIC_INFO_CHANGE: '#a78bfa',
  SECURITY_CHANGE: '#e879f9',
  EA_CHANGE: '#c084fc',
  OBJECT_ID_CHANGE: '#d8b4fe',
  REPARSE_POINT_CHANGE: '#fb923c',
  STREAM_CHANGE: '#2dd4bf',
  HARD_LINK_CHANGE: '#f472b6',
  INDEXABLE_CHANGE: '#94a3b8',
  INTEGRITY_CHANGE: '#a3e635',
  COMPRESSION_CHANGE: '#14b8a6',
  ENCRYPTION_CHANGE: '#ef4444',
  TRANSACTED_CHANGE: '#eab308',
  DESIRED_STORAGE_CLASS_CHANGE: '#64748b',
  CLOSE: '#cbd5e1',
  mft_created: MFT_CREATED,
  mft_modified: MFT_MODIFIED,
}

// A flag no list above names (a newer Windows) still gets a stable colour.
function hashColor(key) {
  let h = 0
  for (const ch of String(key)) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return `hsl(${h % 360}, 70%, 62%)`
}

export function flagColor(key) {
  return FLAG_COLOR[key] || hashColor(key)
}

// 5-step ramp (empty -> full) mixed from the strip background. Computed, so
// every key - including one only a future case contains - has its ramp; a
// colour list without a ramp per key blanks the whole strip (see
// docs/building-a-visualization.md §4).
const BG = [15, 22, 38]
function rgbOf(color) {
  const m = /^#([0-9a-f]{6})$/i.exec(color)
  if (m) return [0, 2, 4].map(i => parseInt(m[1].slice(i, i + 2), 16))
  const el = document.createElement('div')
  el.style.color = color
  document.body.appendChild(el)
  const out = (getComputedStyle(el).color.match(/\d+/g) || [128, 128, 128]).slice(0, 3).map(Number)
  el.remove()
  return out
}
const _ramps = {}
export function flagRamp(key) {
  if (_ramps[key]) return _ramps[key]
  const c = rgbOf(flagColor(key))
  const mix = (t) => `rgb(${BG.map((b, i) => Math.round(b + (c[i] - b) * t)).join(',')})`
  _ramps[key] = ['#0f1626', mix(0.28), mix(0.5), mix(0.75), mix(1)]
  return _ramps[key]
}

export function flagLabel(key) {
  if (key === 'mft_created') return 'Files created (MFT)'
  if (key === 'mft_modified') return 'Files modified (MFT)'
  return String(key).toLowerCase().replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
}

export function fmtFull(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (isNaN(d)) return String(iso)
    return d.toLocaleString(undefined, { year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return String(iso) }
}
export function baseName(path) {
  const p = String(path || '').replace(/\\/g, '/').replace(/\/+$/, '')
  return p.slice(p.lastIndexOf('/') + 1) || p
}

// The per-metric label + a value formatter.
export const METRICS = {
  execution: { label: 'Execution activity', unit: 'active windows', fmt: fmtInt,
    hint: 'How much ran that day — hourly windows in srum_application_usage.' },
  network: { label: 'Network bytes', unit: 'bytes moved', fmt: fmtBytes,
    hint: 'Total bytes sent + received (srum_network_data_usage).' },
  presence: { label: 'User presence', unit: 'input seconds', fmt: fmtDuration,
    hint: 'Keyboard + mouse + focus seconds (srum_app_timeline).' },
  composite: { label: 'Composite score', unit: '/ 100', fmt: (v) => `${v}`,
    hint: 'Normalised blend of execution, network and presence.' },
}
