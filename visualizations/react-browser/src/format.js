// Display formatters. Values are stored raw; formatting lives only here.

export function fmtInt(n) {
  return (n || 0).toLocaleString()
}

export function fmtBytes(n) {
  n = Number(n) || 0
  if (n < 1024) return `${n} B`
  const u = ['KB', 'MB', 'GB', 'TB', 'PB']
  let i = -1
  do { n /= 1024; i++ } while (n >= 1024 && i < u.length - 1)
  return `${n.toFixed(n < 10 ? 2 : 1)} ${u[i]}`
}

export function fmtDay(day) {
  try {
    const d = String(day || '').slice(0, 10)
    return new Date(d + 'T00:00:00').toLocaleDateString(undefined,
      { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' })
  } catch { return day }
}

export function fmtWhen(t) {
  if (!t) return '—'
  const d = String(t).slice(0, 19)
  return d || '—'
}

export function baseName(path) {
  const p = String(path || '').replace(/\\/g, '/').replace(/\/+$/, '')
  return p.slice(p.lastIndexOf('/') + 1) || p
}

// ===== Browser Forensics dashboard: ACTIVITY TYPE = colour =====
// Colour answers "what kind of activity", not "which browser" — a machine with
// one browser reads the same as a machine with six, and the browser is a filter
// instead. Order is the display and legend order.
export const ACTIVITIES = [
  { key: 'visits', label: 'Visits', color: '#4aa8ff', hint: 'Pages actually loaded — History (Chromium) and moz_places (Gecko)' },
  { key: 'searches', label: 'Searches & typed', color: '#39d353', hint: 'What was typed into the omnibox — intent, even for sites never opened' },
  { key: 'downloads', label: 'Downloads', color: '#fbbf24', hint: 'What landed on disk, from where, and whether the browser flagged it' },
  { key: 'cookies', label: 'Cookies set', color: '#a78bfa', hint: 'Session tokens and trackers — these outlive a cleared history' },
  { key: 'cache', label: 'Cache fetches', color: '#22d3ee', hint: 'Resources served from disk, with their real HTTP status' },
]

export const ACTIVITY_KEYS = ACTIVITIES.map(a => a.key)
export const ACTIVITY_LABEL = Object.fromEntries(ACTIVITIES.map(a => [a.key, a.label]))
export const ACTIVITY_COLOR = Object.fromEntries(ACTIVITIES.map(a => [a.key, a.color]))
export const ACTIVITY_HINT = Object.fromEntries(ACTIVITIES.map(a => [a.key, a.hint]))

// Seven solid steps per activity, darkest to brightest, for the heat-map cells.
// Solid rather than alpha: the maps sit on two different card backgrounds and a
// translucent fill reads as a different colour on each.
export const ACTIVITY_RAMPS = {
  visits: ['#0d1f3a', '#12386b', '#17509c', '#1e68cd', '#2f83e8', '#4aa8ff', '#8bc8ff'],
  searches: ['#0c2417', '#0f3d24', '#125632', '#177040', '#219a55', '#39d353', '#7ce88e'],
  downloads: ['#2b1e05', '#453008', '#60430b', '#7d570d', '#a97512', '#fbbf24', '#fcd97a'],
  cookies: ['#1d1533', '#2c1f4f', '#3b296b', '#4d3689', '#6a4cb5', '#a78bfa', '#c9b6fd'],
  cache: ['#062a30', '#08424b', '#0a5a67', '#0d7484', '#119cb2', '#22d3ee', '#7ae6f6'],
}

// Chromium's PageTransition core types, as Browser_Claw stores them. Used to
// tell a page the user CHOSE from one they merely passed through.
export function isTypedTransition(t) {
  const s = String(t || '').toLowerCase()
  return s.includes('typed') || s.includes('keyword') || s.includes('generated')
}

/** Chromium download danger_type: 0 and 7 are "not dangerous". */
export function dangerLabel(v) {
  if (v === null || v === undefined || v === '') return ''
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  if (n === 0 || n === 7) return ''
  return 'flagged'
}
