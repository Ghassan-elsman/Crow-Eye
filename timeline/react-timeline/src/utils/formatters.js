/**
 * Formatters — Time, byte, and cycle value formatting utilities.
 */

/**
 * Format ISO timestamp to display string in strict UTC.
 * 
 * FIX: Bug 5 - Timezone Mismatch for Forensic Accuracy
 * Enforces strict UTC timezone for all timestamp formatting to maintain forensic integrity
 * Prevents local timezone conversion that would compromise evidence accuracy
 * 
 * CRITICAL: All forensic timestamps MUST display in UTC to maintain chain of custody
 * and forensic integrity. This function enforces UTC timezone for all formatting levels.
 * 
 * WARNING: Critical UTC timezone enforcement - DO NOT remove timeZone: 'UTC' from any formatting call
 * Removing UTC enforcement causes timestamps to display in examiner's local timezone, which:
 * - Compromises forensic accuracy and evidence integrity
 * - Breaks timeline correlation with target machine's actual event times
 * - Violates chain of custody requirements for digital forensics
 * - May cause legal/compliance issues with timestamp accuracy
 * All forensic analysis MUST use strict UTC to maintain evidence integrity
 * 
 * @param {string} iso - ISO timestamp string
 * @param {string} level - Format level: 'full', 'short', 'date', 'time'
 * @returns {string} Formatted timestamp in UTC
 * 
 * WARNING: Do NOT remove timeZone: 'UTC' from any formatting call. Local timezone
 * conversion compromises forensic accuracy and evidence integrity.
 */
export function formatTime(iso, level = 'full') {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;

  // Task 5.1.1: Verify all levels use timeZone: 'UTC' - VERIFIED ✓
  // Task 5.1.2: Validation to prevent local timezone conversion
  switch (level) {
    case 'time':
      return d.toLocaleTimeString('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    case 'short':
      return d.toLocaleDateString('en-GB', { timeZone: 'UTC', month: 'short', day: 'numeric' }) + ' ' +
        d.toLocaleTimeString('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit' });
    case 'date':
      return d.toLocaleDateString('en-GB', { timeZone: 'UTC', year: 'numeric', month: 'short', day: 'numeric' });
    case 'full':
    default:
      return d.toLocaleDateString('en-GB', { timeZone: 'UTC', year: 'numeric', month: 'short', day: 'numeric' }) + ' ' +
        d.toLocaleTimeString('en-GB', { timeZone: 'UTC', hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
}

/** Format byte count to human-readable */
export function formatBytes(bytes) {
  if (bytes == null || isNaN(bytes)) return '—';
  if (bytes === 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(Math.abs(bytes)) / Math.log(1024));
  const idx = Math.min(i, units.length - 1);
  return (bytes / Math.pow(1024, idx)).toFixed(idx > 0 ? 1 : 0) + ' ' + units[idx];
}

/** Format CPU cycle time (100ns units) to human-readable duration */
export function formatCycleTime(cycles) {
  if (cycles == null || isNaN(cycles) || cycles === 0) return '—';
  const totalSeconds = cycles / 10_000_000; // 100ns → seconds
  if (totalSeconds < 1) return `${(totalSeconds * 1000).toFixed(0)}ms`;
  if (totalSeconds < 60) return `${totalSeconds.toFixed(1)}s`;
  if (totalSeconds < 3600) return `${(totalSeconds / 60).toFixed(1)}m`;
  return `${(totalSeconds / 3600).toFixed(1)}h`;
}

/** Format duration in seconds to human-readable */
export function formatDuration(seconds) {
  if (seconds == null || isNaN(seconds)) return '—';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

/** Format large numbers with K/M suffixes */
export function formatCount(n) {
  if (n == null || isNaN(n)) return '—';
  if (n < 1000) return String(n);
  if (n < 1_000_000) return (n / 1000).toFixed(1) + 'K';
  return (n / 1_000_000).toFixed(1) + 'M';
}

/** 
 * Convert ISO string to x-position on the SVG timeline.
 * Uses UTC time internally to ensure consistent positioning regardless of local timezone.
 * 
 * @param {string} iso - ISO timestamp (assumed UTC)
 * @param {string} rangeStart - Range start ISO (assumed UTC)
 * @param {number} pxPerHour - Pixels per hour
 * @returns {number} x position in pixels
 */
export function timeToX(iso, rangeStart, pxPerHour) {
  // Task 5.2.2: getTime() returns UTC milliseconds since epoch - safe for UTC calculations
  const t = new Date(iso).getTime();
  const s = new Date(rangeStart).getTime();
  const diffHours = (t - s) / (1000 * 60 * 60);
  return diffHours * pxPerHour;
}

/**
 * Convert x-position back to ISO timestamp.
 * Returns ISO string in UTC format.
 * 
 * @param {number} x - X position in pixels
 * @param {string} rangeStart - Range start ISO (assumed UTC)
 * @param {number} pxPerHour - Pixels per hour
 * @returns {string} ISO timestamp in UTC
 */
export function xToTime(x, rangeStart, pxPerHour) {
  // Task 5.2.2: getTime() and toISOString() both use UTC - safe
  const s = new Date(rangeStart).getTime();
  const ms = (x / pxPerHour) * 60 * 60 * 1000;
  return new Date(s + ms).toISOString();
}

/** Artifact type display configuration */
export const ARTIFACT_CONFIG = {
  sessions:   { label: 'Sessions / Power', color: '#06b6d4', icon: '⚡' },
  srum_app:   { label: 'SRUM App Usage',   color: '#3b82f6', icon: '📊' },
  srum_net:   { label: 'SRUM Network',     color: '#8b5cf6', icon: '🌐' },
  mft_usn:    { label: 'MFT / USN',        color: '#ec4899', icon: '📁' },
  prefetch:   { label: 'Prefetch',         color: '#f59e0b', icon: '🔄' },
  lnk:        { label: 'LNK / Jump Lists', color: '#2ecc71', icon: '🔗' },
  bam:        { label: 'BAM',             color: '#e67e22', icon: '⚙️' },
  registry:   { label: 'Registry',         color: '#9b59b6', icon: '🔑' },
  amcache:    { label: 'AmCache',          color: '#10b981', icon: '📋' },
  shimcache:  { label: 'ShimCache',        color: '#14b8a6', icon: '🗂️' },
  recyclebin: { label: 'Recycle Bin',      color: '#ef4444', icon: '🗑️' },
};

/**
 * Robust identity resolution for forensic artifacts.
 * Handles Windows paths, device paths (\Device\...), and extensions.
 * 
 * IMPORTANT: This function is used for both:
 * - useLinks.js: ID generation for artifact correlation
 * - TimelineView.jsx: posMap key generation for link rendering
 * 
 * Any changes to this function MUST maintain consistency between both use cases.
 * 
 * Processing steps:
 * 1. Normalize path separators (/ → \)
 * 2. Extract last path component (filename)
 * 3. Strip parenthetical suffixes like "(LocalService)"
 * 4. Strip DOS 8.3 short-name tails like "~1"
 * 5. Remove file extension and convert to lowercase
 * 
 * @param {string} str - Raw artifact name/path from forensic data
 * @returns {string} Normalized name (lowercase, no extension, no path)
 * 
 * @example
 * normalizeForensicName("\\Device\\HarddiskVolume3\\Windows\\System32\\cmd.exe")
 * // Returns: "cmd"
 * 
 * @example
 * normalizeForensicName("C:\\Program Files\\App\\svchost.exe (LocalService)")
 * // Returns: "svchost"
 * 
 * @example
 * normalizeForensicName("PROGRA~1\\file.txt")
 * // Returns: "progra"
 */
export function normalizeForensicName(str) {
  if (!str) return '';
  
  // 1. Basic path normalization
  let normalized = str.replace(/\//g, '\\');
  
  // 2. Extract last component (filename)
  const parts = normalized.split('\\');
  let file = parts[parts.length - 1] || parts[parts.length - 2] || normalized;
  
  // 3. Strip parenthetical suffixes, e.g. "svchost.exe (LocalService)"
  file = file.split(' (')[0];
  
  // 4. Strip DOS 8.3 short-name tails, e.g. "PROGRA~1" -> "progra"
  file = file.replace(/~\d+$/, '');
  
  // 5. Final sanitation: lowercase and strip extension
  return file.replace(/\.[^.]+$/, '').toLowerCase().trim();
}
