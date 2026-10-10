// Display formatters. Values are stored raw; formatting lives only here.

export function fmtInt(n) {
  return (n || 0).toLocaleString()
}

// A total too long for a tile: CPU cycles summed over months reach 17 digits
// and wrapped onto a second line. Compact form on screen, exact in the title.
export function fmtCompact(n) {
  n = n || 0
  if (Math.abs(n) < 1e6) return fmtInt(n)
  return n.toLocaleString(undefined, { notation: 'compact', maximumFractionDigits: 1 })
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
