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
/**
 * Internal helper to force a strictly UTC display string: YYYY-MM-DD HH:MM:SS
 */
function toUTCDisplayString(isoOrDate, level = 'full') {
  if (!isoOrDate) return '—';
  const d = new Date(isoOrDate);
  if (isNaN(d.getTime())) return String(isoOrDate);

  const pad = (n) => String(n).padStart(2, '0');
  
  const Y = d.getUTCFullYear();
  const M = pad(d.getUTCMonth() + 1);
  const D = pad(d.getUTCDate());
  const h = pad(d.getUTCHours());
  const m = pad(d.getUTCMinutes());
  const s = pad(d.getUTCSeconds());

  if (level === 'date') return `${Y}-${M}-${D}`;
  if (level === 'time') return `${h}:${m}:${s}`;
  if (level === 'short') return `${M}-${D} ${h}:${m}`;
  return `${Y}-${M}-${D} ${h}:${m}:${s}`;
}

export function formatTime(iso, level = 'full') {
  return toUTCDisplayString(iso, level);
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
  if (!str || typeof str !== 'string') return 'unknown';

  let cleaned = str.trim();
  
  // 1. Normalize path separators and extract filename
  if (cleaned.includes('\\')) cleaned = cleaned.split('\\').pop();
  if (cleaned.includes('/')) cleaned = cleaned.split('/').pop();
  
  // 2. Strip parenthetical suffixes (e.g., "(LocalService)") and DOS 8.3 tails (~1)
  cleaned = cleaned.split('(')[0].split('~')[0].trim();
  
  // 3. Remove file extension and lowercase
  const lastDotIndex = cleaned.lastIndexOf('.');
  if (lastDotIndex > 0) {
    cleaned = cleaned.substring(0, lastDotIndex);
  }
  
  return cleaned.toLowerCase() || 'unknown';
}

/**
 * Extracts a human-readable name from a forensic artifact.
 */
export function getName(p) {
  if (!p) return 'Unknown';
  
  // Manifest-aligned priority naming fields
  const initialName = 
    p.fn_filename || p.file_name || p.Source_Name || p.executable_name || 
    p.original_filename || p.computer_name || p.display_name || p.app_name || 
    p.app_id || p.process_path || p.executable_path ||
    p.search_term || p.program_path || p.command || p.network_name || 
    p.application || p.filename || p.name || p.driver_name ||
    p.program_name || p.displayName || p.file_path || p.target_path || 
    p.path || p.friendly_name || p.value_name || p.app_path || 'Unknown';

  if (initialName === null || initialName === undefined) return 'Unknown';
  if (typeof initialName !== 'string') return String(initialName);
  
  // Clean up Registry/COM paths and Windows paths
  let cleaned = initialName;
  if (cleaned.includes('}')) cleaned = cleaned.split('}').pop();
  if (cleaned.includes('\\')) cleaned = cleaned.split('\\').pop();
  if (cleaned.includes('/')) cleaned = cleaned.split('/').pop();
  
  return cleaned || 'Unknown';
}

/**
 * Alias for getName for manifest compatibility.
 */
export function getForensicName(p) {
  return getName(p);
}

/**
 * Exhaustive list of all forensic timestamp fields from the Crow-Eye manifest.
 */
export const FORENSIC_TS_FIELDS = [
  'timestamp', 'start', 'last_execution', 'last_executed', 'run_times', 'run_times_parsed',
  'Time_Access', 'Time_Creation', 'Time_Modification', 
  'install_date', 'installation_date', 'link_date', 'driver_last_write_time', 'driver_time_stamp',
  'created_on', 'modified_on', 'accessed_on', 'deletion_time',
  'last_install_time', 'scheduled_install_time', 'last_check_time', 'shutdown_time',
  'focus_time', 'created_date', 'modified_date', 'accessed_date', 'access_date',
  'connection_date', 'last_modified', 'last_modified_readable',
  'si_creation_time', 'usn_timestamp', 'EventTimestampUTC', 'creation_time',
  'Last_Run_Time_0', 'Last_Run_Time_1', 'Last_Run_Time_2', 'Last_Run_Time_3',
  'Last_Run_Time_4', 'Last_Run_Time_5', 'Last_Run_Time_6', 'Last_Run_Time_7'
];

/**
 * Extracts all available timestamps from a forensic object.
 * Returns an array of { time: string, field: string }.
 * Handles arrays and semi-colon separated lists (like Prefetch run_times).
 */
/**
 * Robustly cleans a forensic timestamp string for UTC parsing.
 * Handles space-separated dates and missing timezone indicators.
 */
export function cleanForensicDate(ts) {
  if (!ts || ts === 'N/A' || ts === '0s' || ts === 'None') return null;
  if (typeof ts !== 'string') return ts;

  let cleaned = ts.trim();
  
  // 1. Handle MM/DD/YYYY (USA Format) commonly found in Amcache/Registry
  // Captures "02/12/2026 10:00:00" -> "2026-02-12 10:00:00"
  const usaMatch = cleaned.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(.*)/);
  if (usaMatch) {
    const [_, m, d, y, time] = usaMatch;
    cleaned = `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}${time || ''}`;
  }

  // 2. Handle common space separator: "2026-04-16 10:00:00" -> "2026-04-16T10:00:00"
  if (cleaned.includes(' ') && !cleaned.includes('T')) {
    cleaned = cleaned.replace(' ', 'T');
  }

  // 3. Force UTC if no offset or Z is present
  if (!cleaned.includes('Z') && !cleaned.includes('+') && !/-\d{2}:\d{2}$/.test(cleaned)) {
    cleaned = cleaned + 'Z';
  }

  return cleaned;
}

/**
 * Extracts all available timestamps from a forensic object.
 * Returns an array of { time: string, field: string }.
 */
export function getForensicTimestamps(p) {
  const extracted = [];
  if (!p || typeof p !== 'object') return extracted;

  FORENSIC_TS_FIELDS.forEach(f => {
    const val = p[f];
    if (val) {
      const processVal = (v) => {
        if (!v) return;
        const cleaned = cleanForensicDate(v);
        const d = new Date(cleaned);
        const ts = d.getTime();
        if (isNaN(ts)) return;

        // Filter out forensic "null" dates (e.g. 1601-01-01, 1700-01-01)
        if (d.getUTCFullYear() < 1980) return;

        extracted.push({ time: cleaned, field: f });
      };

      if (Array.isArray(val)) {
        val.forEach(processVal);
      } else if (typeof val === 'string' && val.includes(';')) {
        val.split(';').forEach(v => processVal(v.trim()));
      } else {
        processVal(val);
      }
    }
  });

  return extracted;
}

/**
 * Extracts a single primary timestamp from a forensic object for sorting or fingerprinting.
 */
export function getPrimaryTimestamp(obj) {
  if (!obj) return null;
  const raw = obj.timestamp || obj.start || obj.last_execution || obj.last_executed ||
    (Array.isArray(obj.run_times) ? obj.run_times[0] : obj.run_times) ||
    obj.Time_Access || obj.Time_Creation || obj.Time_Modification ||
    obj.si_creation_time || obj.usn_timestamp || obj.link_date ||
    obj.install_date || obj.installation_date || obj.last_install_time || obj.scheduled_install_time ||
    obj.driver_time_stamp || obj.driver_last_write_time || obj.last_modified || obj.last_modified_readable ||
    obj.deletion_time || obj.access_date || obj.accessed_date || obj.last_check_time ||
    obj.modified_date || obj.created_date || obj.first_connected || obj.last_connected || obj.last_removed || obj.connection_date ||
    obj.EventTimestampUTC || obj.creation_time || obj.created_on || obj.modified_on || obj.accessed_on ||
    obj.shutdown_time || obj.focus_time;

  return cleanForensicDate(raw);
}

/**
 * Generates a unique, consistent ID for a forensic event.
 * Used for React keys, linking, and posMap registration.
 */
export function getForensicId(type, timestamp, field, name) {
  const cleaned = cleanForensicDate(timestamp);
  if (!cleaned) return `${type}-0-${field}-unknown`.toLowerCase();

  const t = new Date(cleaned).getTime() || 0;
  const norm = normalizeForensicName(name);
  // Format: {type}-{timestamp_ms}-{field}-{normalized_name}
  return `${type}-${t}-${field}-${norm}`.toLowerCase();
}

/**
 * Centralized Discovery Engine (Version 2.0 - Key Agnostic)
 * Scans the entire data object for forensic artifacts.
 * This ensures that even if a new Registry table is added to the manifest, 
 * it is automatically detected and visualized.
 */
export function getArtifactSources(data) {
  if (!data) return [];
  
  const allItems = [];
  const processedKeys = new Set(['sessions', 'srum_app', 'srum_net', 'mft_usn', 'mft', 'aggregated', 'links']);
  // Unique filter to prevent scanning the same array twice
  const seenArrays = new Set();
  
  // 1. Scan top-level keys for artifacts (Prefetch, LNK, BAM, etc.)
  Object.keys(data).forEach(key => {
    if (processedKeys.has(key)) return;
    const items = data[key];
    
    if (Array.isArray(items)) {
      if (seenArrays.has(items)) return;
      seenArrays.add(items);
      items.forEach(item => {
        // Inject source context if missing for forensic icons/coloring
        if (!item.tsType && !item.artifact_type) item.tsType = key;
        allItems.push(item);
      });
    } else if (items && typeof items === 'object') {
      // 2. Scan nested structures (e.g. data.amcache.application_files, data.registry.UserAssist)
      Object.keys(items).forEach(subKey => {
        const subItems = items[subKey];
        if (Array.isArray(subItems)) {
          if (seenArrays.has(subItems)) return;
          seenArrays.add(subItems);
          subItems.forEach(item => {
            if (!item.tsType && !item.artifact_type) item.tsType = subKey;
            allItems.push(item);
          });
        }
      });
    }
  });

  return allItems;
}

