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

// A "flagged" event needs analyst review.
export function isFlagged(event) {
  return event.severity === 'suspicious' || event.severity === 'critical'
}

// activity -> { label } for the category pill. Icon comes from icons.jsx.
export const ACTIVITY_META = {
  // Browser databases (browser_analysis.db). web_browsing already existed for
  // the registry-typed-URL rule and is reused by the real history rule.
  file_download: { label: 'Download' },
  application_state: { label: 'App state' },
  configuration_change: { label: 'Setting changed' },
  account_sync: { label: 'Account sync' },
  extension_install: { label: 'Browser extension' },
  credential_storage: { label: 'Stored credentials' },
  anti_forensics: { label: 'Anti-forensics' },
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
