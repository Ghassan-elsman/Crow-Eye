// Crow-Eye "Sentinel" palette (prototype). Dark navy base, crimson signal
// accent, green = high confidence, blue = a person did it, gray = the computer.
export const COLORS = {
  bg: '#070911',
  panel: '#0d121f',
  panelHover: '#121a2b',
  border: '#1c2333',
  borderStrong: '#2a3349',
  text: '#e9ecf4',
  textDim: '#8c95ab',
  textFaint: '#525b72',
  red: '#ff3b56',
  green: '#34e0a1',
  blue: '#4f8eff',
  gray: '#9aa3b8',
  indigo: '#8b8cf8',
  amber: '#f0a93b',
}

// Semantic actor coding: blue = a person, gray = the computer.
export const ACTOR_STYLE = {
  User: { color: '#4f8eff', bg: 'rgba(79,142,255,0.13)', label: 'User action' },
  Application: { color: '#9aa3b8', bg: 'rgba(154,163,184,0.13)', label: 'Program action' },
  System: { color: '#9aa3b8', bg: 'rgba(154,163,184,0.13)', label: 'System action' },
  '': { color: '#9aa3b8', bg: 'rgba(154,163,184,0.13)', label: 'Unattributed' },
}

// Behavior class -> friendly label (kept for filters).
export const CLASS_STYLE = {
  user: { color: '#4f8eff', label: 'User' },
  application: { color: '#9aa3b8', label: 'Program' },
  system_app: { color: '#9aa3b8', label: 'System program' },
  system: { color: '#9aa3b8', label: 'System' },
}

export const SEVERITY_STYLE = {
  routine: { color: '#8c95ab', bg: 'rgba(154,163,184,0.12)', label: 'Routine' },
  notable: { color: '#f0a93b', bg: 'rgba(240,169,59,0.13)', label: 'Notable' },
  suspicious: { color: '#ff3b56', bg: 'rgba(255,59,86,0.13)', label: 'Suspicious' },
  critical: { color: '#ffffff', bg: '#ff3b56', label: 'Critical' },
}

// ACTOR COLOURS - what drove an activity, and nothing else (Ghassan,
// 2026-11-03: every card about people, AI agents or apps and automation wears
// its toggle's colour; the meaning is kept for later use). One hue per
// Driven-by toggle:
//   blue   #4f8eff  people: a person at the keyboard, or a person remotely
//   cyan   #22d3ee  AI agents: what an agent ran, from its own session record
//   fuchsia #e879f9 apps and automation: a program by itself, a script
//   slate  #525b72  not decided by the evidence (no toggle)
// Never red (urgent) or amber (the "notable" severity); not violet either,
// which the Sentinel console uses for "waiting" and "held". An actor colour is
// a stripe, a dot, an outline or text - never a filled background (a blue
// fill means "selected" there). Agreed with Crow-Eye Sentinel's console,
// which uses the same values for its actor roles.
// MEASURE: a number's kind (bytes, seconds, counts) on a fact badge carries no
// hue - the icon in the unit grey, the value in white; what tells a measure is
// its icon and card, which keeps colour free for meaning. Agreed with Crow-Eye
// Sentinel's console (roles "unit" #A3A8B3 and "value").
export const MEASURE_COLOR = '#a3a8b3'
export const ACTOR_COLOR = { people: '#4f8eff', ai: '#22d3ee', apps: '#e879f9', unknown: '#525b72' }
export const OPERATOR_STYLE = {
  person: { label: 'Person at the keyboard', color: ACTOR_COLOR.people, bg: 'transparent' },
  remote_person: { label: 'Person, remotely', color: ACTOR_COLOR.people, bg: 'transparent' },
  program: { label: 'Program by itself', color: ACTOR_COLOR.apps, bg: 'transparent' },
  automation: { label: 'Automation', color: ACTOR_COLOR.apps, bg: 'transparent' },
  ai_agent: { label: 'AI agent', color: ACTOR_COLOR.ai, bg: 'transparent' },
}
// Whether the program was the window in front, or running behind, at that moment.
export const APP_STATE_STYLE = {
  foreground: { label: 'In front', color: '#4f8eff', bg: 'rgba(79,142,255,0.10)' },
  background: { label: 'In the background', color: '#9aa3b8', bg: 'rgba(154,163,184,0.10)' },
}

// The same verdict as one key per activity (uba/engine/event_store.py
// DRIVER_SQL): the Who drove it tab's tiles, rows and bars, and the filter
// they open. The desktop names an AI agent only from the agent's own session
// record; cyan, not red - red is for what is urgent.
export const DRIVERS = ['person', 'remote', 'program', 'script', 'ai_agent', 'unknown']
export const DRIVER_STYLE = {
  person: { label: 'Person at the keyboard', short: 'Person', color: ACTOR_COLOR.people, group: 'people' },
  remote: { label: 'Person, remotely', short: 'Remote', color: ACTOR_COLOR.people, group: 'people' },
  program: { label: 'Program by itself', short: 'Program', color: ACTOR_COLOR.apps, group: 'apps' },
  script: { label: 'Script or automation', short: 'Script', color: ACTOR_COLOR.apps, group: 'apps' },
  ai_agent: { label: 'AI agent (its own session record)', short: 'AI agent', color: ACTOR_COLOR.ai, group: 'ai' },
  unknown: { label: 'Not decided by the evidence', short: 'Not decided', color: ACTOR_COLOR.unknown, group: '' },
}

// A colour at a given opacity, for a toggle's tinted fill (QtWebEngine's
// Chromium has no color-mix()).
export function tint(hex, a) {
  const h = String(hex || '#8b8cf8').replace('#', '')
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`
}
// The style of a toggle chip in its own colour: on, a tinted fill and border.
export function chipStyle(color, on) {
  return { '--c': color, '--t': tint(color, on ? 0.16 : 0.08) }
}

// The filter bar's "Driven by" toggles: three groups of the drivers above,
// all on by default. Turning one off hides those activities everywhere.
export const DRIVER_GROUPS = [
  { key: 'people', label: 'People', drivers: ['person', 'remote'], color: ACTOR_COLOR.people,
    title: 'A person at the keyboard, or a person signed in remotely' },
  { key: 'ai', label: 'AI agents', drivers: ['ai_agent'], color: ACTOR_COLOR.ai,
    title: "What an AI agent ran, from the agent's own session record" },
  { key: 'apps', label: 'Apps & automation', drivers: ['program', 'script'], color: ACTOR_COLOR.apps,
    title: 'A program by itself, or a script or other automation' },
]

// The driver key of one activity, as event_store.DRIVER_SQL computes it.
export function driverOf(event) {
  if (event.rule_id === 'ai_agent_turn' || event.operator_kind === 'ai_agent') return 'ai_agent'
  return { automation: 'script', person: 'person', remote_person: 'remote', program: 'program' }[event.operator] || 'unknown'
}

export function operatorLabel(event) {
  if (driverOf(event) === 'ai_agent') return { ...OPERATOR_STYLE.ai_agent, label: 'AI agent' }
  const s = OPERATOR_STYLE[event.operator]
  if (!s) return null
  if (event.operator === 'automation' && event.operator_kind === 'script') return { ...s, label: 'Script or automation' }
  return s
}

// A "flagged" event needs analyst review.
export function isFlagged(event) {
  return event.severity === 'suspicious' || event.severity === 'critical'
}

// activity -> { label } for the category pill. Icon comes from icons.jsx.
export const ACTIVITY_META = {
  // 2026-11-03: printing, Remote Desktop out, cloud sync, USB copies, files gathered.
  printer_added: { label: 'Printer' },
  remote_desktop_out: { label: 'Remote Desktop' },
  cloud_sync: { label: 'Cloud sync' },
  usb_copy: { label: 'USB copy' },
  files_collected: { label: 'Files gathered' },
  input: { label: 'Keyboard & mouse' },
  // AI agent sessions (ai_agents.db): Claude Code, Gemini CLI, Codex.
  ai_agent_session: { label: 'AI agent session' },
  ai_agent_command: { label: 'AI agent commands' },
  // Browser databases (browser_analysis.db). web_browsing already existed for
  // the registry-typed-URL rule and is reused by the real history rule.
  file_download: { label: 'Download' },
  application_state: { label: 'App state' },
  configuration_change: { label: 'Setting changed' },
  account_sync: { label: 'Account sync' },
  extension_install: { label: 'Browser extension' },
  credential_storage: { label: 'Stored credentials' },
  anti_forensics: { label: 'Anti-forensics' },
  // Round 11: curated site categories (uba/config/site_categories.json).
  web_search: { label: 'Web search' },
  site_visit: { label: 'Site visit' },
  file_upload: { label: 'Upload (inferred)' },
  communication_app: { label: 'Chat app' },
  crypto_wallet: { label: 'Crypto wallet' },
  open_tabs: { label: 'Open tabs' },
  media_playback: { label: 'Media' },
  logon: { label: 'Session' },
  logoff: { label: 'Session' },
  unlock: { label: 'Session' },
  failed_logon: { label: 'Failed sign-in' },
  app_launch: { label: 'App launch' },
  program_run: { label: 'App execution' },
  process_created: { label: 'Process start' },
  program_presence: { label: 'Program present' },
  app_usage: { label: 'App usage' },
  app_installed: { label: 'App install' },
  folder_browsing: { label: 'Navigation' },
  file_opened: { label: 'File open' },
  file_created: { label: 'File create' },
  file_edited: { label: 'File edit' },
  file_renamed: { label: 'File rename' },
  file_copied: { label: 'File copy' },
  file_deleted: { label: 'File delete' },
  file_soft_deleted: { label: 'Recycle Bin' },
  usb_connected: { label: 'Device' },
  device_present: { label: 'Device' },
  web_browsing: { label: 'Web' },
  local_search: { label: 'Search' },
  network_usage: { label: 'Network' },
  network_changed: { label: 'Network' },
  network_session: { label: 'Network' },
  service_installed: { label: 'Service' },
  driver_present: { label: 'Driver' },
  autostart: { label: 'Persistence' },
  boot_shutdown: { label: 'Power' },
  time_changed: { label: 'Time change' },
  log_cleared: { label: 'Log cleared' },
  privileged_logon: { label: 'Admin logon' },
  runas: { label: 'Credentials' },
  account_enumeration: { label: 'Account lookup' },
  account_management: { label: 'Account admin' },
  windows_update: { label: 'Update' },
}

export function activityLabel(activity) {
  return (ACTIVITY_META[activity] && ACTIVITY_META[activity].label) || activity
}

// Confidence -> pill { label, color } (green = high, amber = qualified).
export const CONFIDENCE_TIER = {
  corroborated: { label: 'High confidence', color: '#34e0a1' },
  'log-only': { label: 'From event log', color: '#4f8eff' },
  'artifact-only': { label: 'From disk evidence', color: '#f0a93b' },
  presence: { label: 'Presence only', color: '#f0a93b' },
  inference: { label: 'Inferred', color: '#f0a93b' },
}

export const CONFIDENCE_LABEL = {
  corroborated: 'Confirmed by Windows event log',
  'artifact-only': 'From disk evidence',
  'log-only': 'From Windows event log',
  presence: 'Presence evidence only',
  inference: 'Inferred (not certain)',
}

// Friendly evidence-source names for the inline proof list, by (db, table).
const SOURCE_BY_TABLE = {
  browser_history: 'Browser — history',
  browser_gecko_history: 'Browser — history (Firefox)',
  browser_downloads: 'Browser — downloads',
  browser_preferences: 'Browser — profile preferences',
  browser_extensions: 'Browser — extensions',
  browser_credentials: 'Browser — saved logins',
  browser_gecko_credentials: 'Browser — saved logins (Firefox)',
  browser_payments: 'Browser — payment data',
  browser_addresses: 'Browser — saved addresses',
  browser_cookies: 'Browser — cookies',
  browser_dips: 'Browser — site engagement',
  browser_gecko_downloads: 'Browser — downloads (Firefox)',
  browser_gecko_cookies: 'Browser — cookies (Firefox)',
  browser_shortcuts: 'Browser — address-bar entries',
  browser_sessions: 'Browser — session (open tabs)',
  browser_gecko_sessions: 'Browser — session (Firefox)',
  browser_media_history: 'Browser — media history',
  browser_metadata: 'Browser — collected profiles',
  browser_files: 'Browser — collected profile files',
  SecurityLogs: 'Event Log — Security',
  SystemLogs: 'Event Log — System',
  ApplicationLogs: 'Event Log — Application',
  journal_events: 'USN Journal',
  mft_usn_correlated: 'MFT + USN (correlated)',
  UserAssist: 'UserAssist',
  BAM: 'Background Activity (BAM)',
  prefetch_data: 'Prefetch',
  shimcache_entries: 'ShimCache',
  Shellbags: 'ShellBags',
  LNK_Files: 'LNK Files',
  Automatic_JumpLists: 'Jump List',
  Custom_JumpLists: 'Jump List (custom)',
  recycle_bin_entries: 'Recycle Bin',
  srum_application_usage: 'SRUM — app usage',
  srum_network_data_usage: 'SRUM — network',
  srum_network_connectivity: 'SRUM — connectivity',
  InventoryApplication: 'AmCache — applications',
  InventoryApplicationFile: 'AmCache — files',
  InventoryApplicationShortcut: 'AmCache — shortcuts',
  InventoryDriverBinary: 'AmCache — drivers',
  InventoryDevicePnp: 'AmCache — devices',
  MUICache: 'MUICache',
  USBDevices: 'Registry — USB',
  USBStorageDevices: 'Registry — USB storage',
  InstalledSoftware: 'Registry — installed software',
  printer_connections: 'Registry — printers',
  RDPClientMRU: 'Registry — Remote Desktop history',
  srum_app_timeline: 'SRUM — keyboard, mouse and focus time',
  ai_agent_sessions: 'AI agent — sessions',
  ai_agent_steps: 'AI agent — prompts, commands and file changes',
  SystemServices: 'Registry — services',
  AutoStartPrograms: 'Registry — autostart',
  Network_list: 'Registry — networks',
  BrowserHistory: 'Registry — browser history',
  RecentDocs: 'Registry — recent docs',
  TimeZoneInfo: 'Registry — time zone',
}

export function evidenceSourceLabel(ref) {
  return SOURCE_BY_TABLE[ref.table] || ref.table || ref.db || 'Evidence'
}

export function evidenceDetail(ref) {
  const n = ref.count || (ref.rowids ? ref.rowids.length : 0)
  const noun = n === 1 ? 'record' : 'records'
  const role = ref.role === 'corroborating' ? ' (corroborating)' : ''
  return `${n.toLocaleString()} ${noun}${role}`
}

export function actorLabel(actorType, actorName) {
  if (!actorType && !actorName) return 'Unattributed'
  return actorName || actorType
}

// The user to display on an activity, with an explicit basis so a labelled
// (logged-in) user is never mistaken for a proven actor.
export function displayUser(event) {
  if (event.actor_type === 'User' && event.actor_name) {
    return { text: event.actor_name, basis: 'definitive', definitive: true }
  }
  if (event.session_user) {
    return { text: `${event.session_user}`, basis: 'session', definitive: false }
  }
  if (event.actor_type === 'System') {
    return { text: 'System', basis: 'system', definitive: true }
  }
  if (event.actor_type === 'Application') {
    return { text: event.actor_name || 'Program', basis: 'app', definitive: true }
  }
  return { text: 'Unattributed', basis: 'none', definitive: false }
}

// Windows logon types, for the Sign-ins view. Mirrors
// uba/utils/log_parser.py::LOGON_TYPE_LABELS — keep the two in step.
export const LOGON_TYPE_LABEL = {
  2: 'At the keyboard', 3: 'Over the network', 4: 'Scheduled task',
  5: 'Windows service', 7: 'Unlocked the screen', 8: 'Network (cleartext)',
  9: 'Run as another user', 10: 'Remote Desktop', 11: 'Cached sign-in',
}

export function logonTypeLabel(type) {
  return LOGON_TYPE_LABEL[Number(type)] || `Logon type ${type}`
}

// How a session ended. 'open' must never read as a measured end — there is no
// evidence for one, so the UI says so instead of showing a duration.
export const END_BASIS_STYLE = {
  logoff: { label: 'Signed out', color: '#8c95ab' },
  signout: { label: 'Chose Sign out', color: '#34e0a1' },
  'same-second': { label: 'Same second', color: '#f0a93b' },
  open: { label: 'No sign-out recorded', color: '#f0a93b' },
}

export const END_BASIS_NOTE = {
  logoff: 'Windows recorded the sign-out for this session.',
  signout: 'The person chose Sign out; Windows recorded it.',
  'same-second': 'Windows recorded the sign-out in the same second as the sign-in — '
    + 'typically the session being torn down at shutdown.',
  open: 'No sign-out was recorded, so how long this session lasted is not known. '
    + 'The window below is only how far the evidence can place it.',
}

// Durations are only ever shown when the evidence supports one.
export function durationLabel(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  const h = Math.floor(s / 3600)
  const m = Math.round((s % 3600) / 60)
  return m ? `${h}h ${m}m` : `${h}h`
}

export const USER_BASIS_NOTE = {
  session: 'was the signed-in user at this time (not proof they performed it)',
  definitive: 'named by the evidence itself',
  system: 'performed by Windows',
  app: 'performed by a program',
  none: 'no user could be determined from the evidence',
}
