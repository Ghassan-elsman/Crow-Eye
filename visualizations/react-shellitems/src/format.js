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

// ===== Shell Items dashboard: artifact SOURCE = colour =====
// The seven Windows shell-item channels, in display (and colour) order.
export const SOURCES = [
  { key: 'shellbags', label: 'Shellbags (BagMRU)', color: '#4aa8ff', hint: 'BagMRU — folders the user browsed, with embedded FAT MAC times' },
  { key: 'recentdocs', label: 'RecentDocs', color: '#39d353', hint: 'Files & folders recently opened, per extension, in MRU order' },
  { key: 'opensave', label: 'OpenSaveMRU', color: '#fbbf24', hint: 'ComDlg32 OpenSavePidlMRU — files an Open/Save dialog touched' },
  { key: 'lastvisited', label: 'LastSaveMRU (LastVisited)', color: '#22d3ee', hint: 'ComDlg32 LastVisitedPidlMRU — which app used a dialog, in which folder' },
  { key: 'typedpaths', label: 'TypedPaths', color: '#a78bfa', hint: 'Paths typed into the Explorer address bar' },
  { key: 'runmru', label: 'RunMRU', color: '#f43f5e', hint: 'Commands typed into the Run box' },
  { key: 'search', label: 'Search', color: '#94a3b8', hint: 'WordWheelQuery — terms typed into the Explorer search bar' },
  { key: 'dialogapps', label: 'CIDSizeMRU', color: '#fb923c', hint: 'ComDlg32 CIDSizeMRU — programs that opened an Open/Save dialog (no path)' },
  { key: 'taskband', label: 'Taskbar pins', color: '#e879f9', hint: 'Explorer\\Taskband — items pinned to the taskbar (shell-item list)' },
  { key: 'mountpoints', label: 'MountPoints2', color: '#2dd4bf', hint: 'Volumes and network shares this user mounted' },
  { key: 'office', label: 'Office MRU', color: '#f97316', hint: 'Office File / Place MRU — files and folders opened in Word, Excel, PowerPoint' },
  { key: 'typedurls', label: 'TypedURLs', color: '#818cf8', hint: 'Internet Explorer TypedURLs — addresses typed into the address bar' },
  { key: 'rdp', label: 'RDPClientMRU', color: '#fda4af', hint: 'Terminal Server Client MRU — Remote Desktop servers typed' },
  { key: 'recentapps', label: 'RecentApps', color: '#a3e635', hint: 'Search\\RecentApps — recently used apps (Windows 10)' },
  { key: 'appmru', label: 'App MRUs', color: '#facc15', hint: 'Per-application MRUs — 7-Zip, WinSCP, PuTTY, FileZilla…' },
  { key: 'regedit', label: 'Regedit last key', color: '#cbd5e1', hint: 'Applets\\Regedit LastKey — the last key open in Registry Editor' },
  { key: 'muicache', label: 'MUICache', color: '#67e8f9', hint: 'Shell\\MuiCache — programs this user launched (name + company; no time recorded)' },
  { key: 'shellfolders', label: 'User Shell Folders', color: '#86efac', hint: 'Explorer\\User Shell Folders — where each known folder points (no time recorded)' },
  { key: 'shellext', label: 'Shell extensions', color: '#fca5a5', hint: 'Shell open commands, icon overlay handlers, delay-load shell objects (no time recorded)' },
]
export const SOURCE_COLOR = Object.fromEntries(SOURCES.map(s => [s.key, s.color]))
export const SOURCE_LABEL = Object.fromEntries(SOURCES.map(s => [s.key, s.label]))
export const SOURCE_HINT = Object.fromEntries(SOURCES.map(s => [s.key, s.hint]))

// 5-step ramp per source (empty -> full) for its heat-strip.
export const SOURCE_RAMPS = {
  shellbags: ['#0f1626', '#0b3b63', '#125089', '#2a7fd4', '#4aa8ff'],
  recentdocs: ['#0f1626', '#0e4429', '#116b34', '#20a34a', '#39d353'],
  opensave: ['#0f1626', '#5a3a12', '#8a5a1a', '#c08a1f', '#fbbf24'],
  lastvisited: ['#0f1626', '#0b4a52', '#0e6b78', '#18a0b0', '#22d3ee'],
  typedpaths: ['#0f1626', '#3a1d63', '#5a2f8f', '#7d4fc0', '#a78bfa'],
  runmru: ['#0f1626', '#5c1526', '#8f1d34', '#c62c48', '#f43f5e'],
  search: ['#0f1626', '#2b3444', '#48566b', '#6b7a90', '#94a3b8'],
  // Every key in SOURCES needs a ramp: the strip reads one per source row,
  // and a missing one throws during render and blanks the whole dashboard.
  dialogapps: ['#0f1626', '#5a2a0e', '#8a4214', '#c2621b', '#fb923c'],
  taskband: ['#0f1626', '#4a1d52', '#76308a', '#b04fc6', '#e879f9'],
  mountpoints: ['#0f1626', '#0e3f3a', '#13635b', '#1f9c8f', '#2dd4bf'],
  office: ['#0f1626', '#552711', '#8a3c14', '#c7581a', '#f97316'],
  typedurls: ['#0f1626', '#2a2d5e', '#41468f', '#5f66c4', '#818cf8'],
  rdp: ['#0f1626', '#5a2f37', '#8a4653', '#c96f7e', '#fda4af'],
  recentapps: ['#0f1626', '#33461a', '#4f6d22', '#78a62c', '#a3e635'],
  appmru: ['#0f1626', '#544511', '#866c17', '#c19c1d', '#facc15'],
  regedit: ['#0f1626', '#2f3744', '#4c5666', '#7d8796', '#cbd5e1'],
  muicache: ['#0f1626', '#1d4650', '#2a6b7a', '#44a7bd', '#67e8f9'],
  shellfolders: ['#0f1626', '#24452f', '#356b47', '#55a872', '#86efac'],
  shellext: ['#0f1626', '#4d2a2a', '#7a3e3e', '#bb6464', '#fca5a5'],
}

// The target's location — a secondary axis (filter + insights), not the colour.
export const LOCATIONS = [
  { key: 'localfixed', label: 'Local (fixed C:)' },
  { key: 'userprofile', label: 'User profile' },
  { key: 'removable', label: 'Removable / other volume' },
  { key: 'network', label: 'Network share' },
  { key: 'other', label: 'Other' },
]
export const LOC_LABEL = Object.fromEntries(LOCATIONS.map(l => [l.key, l.label]))

// Short glyphs for the shell-item type of a row.
export const TYPE_LABEL = {
  folder: 'folder', file: 'file', volume: 'volume', network: 'network',
  command: 'command', search: 'search', application: 'program', other: 'item',
  pinned: 'pinned', url: 'url', 'remote host': 'remote host', 'registry key': 'reg key', item: 'item',
  'shell extension': 'shell ext',
}
