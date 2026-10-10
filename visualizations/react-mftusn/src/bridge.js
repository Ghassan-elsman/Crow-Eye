/**
 * QWebChannel bridge to the Python MftUsnBridge. Same shape as the SRUM app's
 * bridge: wait for qt.webChannelTransport, resolve with channel.objects.bridge;
 * in a plain browser resolve with a mock so the UI runs standalone.
 */
let bridgePromise = null

function mockBridge() {
  // Standalone `npm run dev` only: the shapes the Python bridge returns.
  const pad = (n) => String(n).padStart(2, '0')
  const days = []
  const start = new Date('2026-01-01')
  for (let i = 0; i < 280; i++) { const d = new Date(start); d.setDate(d.getDate() + i); days.push(d.toISOString().slice(0, 10)) }
  const flags = ['FILE_CREATE', 'FILE_DELETE', 'RENAME_NEW_NAME', 'DATA_EXTEND', 'BASIC_INFO_CHANGE', 'CLOSE']
  const series = {}
  const combined = {}
  const mk = (key, scale, from) => {
    const buckets = days.map((d, i) => ({ key: d, value: i < from ? 0 : Math.round(scale * Math.abs(Math.sin(i / 5)) * Math.random()) }))
    buckets.forEach(b => { combined[b.key] = (combined[b.key] || 0) + b.value })
    series[key] = { buckets, max: Math.max(1, ...buckets.map(b => b.value)) }
  }
  mk('mft_created', 120, 0); mk('mft_modified', 220, 0)
  flags.forEach((f, i) => mk(f, 300 / (i + 1), 250))
  const rows = [{ key: 'mft_created', label: 'Files created (MFT)', group: 'mft', total: 1 },
    { key: 'mft_modified', label: 'Files modified (MFT)', group: 'mft', total: 1 }]
    .concat(flags.map(f => ({ key: f, label: f.replace(/_/g, ' '), group: 'usn', total: 1 })))
  const ev = (i) => ({ id: `C:${1000 + i}:2`, rec: 1000 + i, name: `file${i}.tmp`,
    path: `Users/Ann/AppData/Local/Temp/dir${i % 7}/file${i}.tmp`, pathFrom: i % 3 ? 'journal' : 'mft',
    t: `2026-10-07 ${pad(i % 24)}:${pad(i % 60)}:00`, hour: i % 24, flags: [flags[i % flags.length], 'CLOSE'],
    cats: [], size: 1234, inMft: i % 3 === 0 })
  const byHour = Object.fromEntries(flags.map((f, j) => [f, Array.from({ length: 24 }, (_, h) => Math.round(50 * Math.abs(Math.sin((h + j) / 3))))]))
  const json = (o) => Promise.resolve(JSON.stringify(o))
  return {
    getMftUsnBounds: () => json({ hasData: true, min: days[0], max: days[days.length - 1],
      usnMin: days[250], usnMax: days[days.length - 1], mftMin: days[0], mftMax: days[days.length - 1],
      volumes: ['C'], hasVolume: true, hasAds: true }),
    getMftUsnTimelines: () => json({ rows, series,
      combined: days.map(d => ({ key: d, value: combined[d] || 0 })),
      totals: { usnEvents: 5000, mftCreated: 900, mftModified: 1800 } }),
    getMftUsnOverview: () => json({
      totals: { files: 200314, directories: 51372, usnEvents: 283585, withEvents: 52006, created: 160515, deletedEvents: 34311 },
      anomalies: { timestompCandidates: { count: 0, subjects: [] }, usnGaps: { count: 0, subjects: [] },
        deletedButPresent: { count: 0, subjects: [] }, ads: { count: 0, subjects: [] } },
      byFlag: Object.fromEntries(flags.map((f, i) => [f, 1000 * (i + 1)])),
      topDirs: [{ dir: 'Windows/System32', n: 900 }], topExts: [{ ext: 'dll', n: 400 }] }),
    getMftUsnWindowDetail: () => json({ events: Array.from({ length: 60 }, (_, i) => ev(i)), total: 1200, page: 0, pageSize: 500,
      byHour, byFlag: Object.fromEntries(flags.map(f => [f, 100])), topDirs: [{ dir: 'Windows/Temp', n: 300 }],
      topExts: [{ ext: 'tmp', n: 300 }],
      mft: { created: { total: 3, files: [{ id: 'C:5:5', name: 'a.txt', path: 'Users/Ann/a.txt', t: '2026-10-07 10:00:00' }] },
        modified: { total: 0, files: [] } } }),
    getMftUsnDayEvents: (a) => json({ events: Array.from({ length: 40 }, (_, i) => ev(i)), total: 1200,
      page: JSON.parse(a || '{}').page || 0, pageSize: 500 }),
    getMftUsnDayFiles: (a) => json({ total: 450, page: JSON.parse(a || '{}').page || 0, pageSize: 200,
      files: [{ id: 'C:6:1', name: 'b.txt', path: 'Users/Ann/b.txt', t: '2026-10-07 11:00:00' }] }),
    getMftUsnDayRenames: (a) => json({ total: 2, page: JSON.parse(a || '{}').page || 0, pageSize: 200,
      rows: [{ id: 'C:1000:2', t: '2026-10-07 10:00:00', old: 'draft.docx', new: 'report.docx',
        oldDir: 'Users/Ann/Documents', newDir: 'Users/Ann/Documents', move: false }] }),
    getMftUsnAll: (a) => json({ kind: JSON.parse(a || '{}').kind || 'events', total: 60, pageSize: 500,
      rows: Array.from({ length: 20 }, (_, i) => ev(i)) }),
    getMftUsnFileDetail: () => json({ id: 'C:1000:2', rec: 1000, seq: 2, volume: 'C', filename: 'report.docx',
      path: 'Users/Ann/Documents/report.docx', pathFrom: 'mft', names: ['report.docx'], inMft: true,
      isDir: 0, deleted: 0, size: 284219, si: {}, fnTimes: {}, flags: [], eventsTotal: 1,
      events: [{ t: '2026-10-07 10:00:00', flags: ['FILE_CREATE', 'CLOSE'], reason: 'FILE_CREATE | CLOSE' }] }),
    _mock: true,
  }
}

export function getBridge() {
  if (bridgePromise) return bridgePromise
  bridgePromise = new Promise((resolve) => {
    if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {
      new window.QWebChannel(window.qt.webChannelTransport, (channel) => resolve(channel.objects.bridge))
    } else {
      console.warn('[mftusn] QWebChannel not available - using mock data')
      resolve(mockBridge())
    }
  })
  return bridgePromise
}

// Data getters run off Crow-Eye's GUI thread when the bridge offers callAsync
// (visualizations/async_bridge.py): the answer comes back on asyncResult, so
// the window and the loading overlay keep painting during a long query.
// Anything else (dialog openers), the mock, and an older bridge stay plain
// synchronous calls. Same block in every dashboard and react-timeline.
let asyncSeq = 0
const asyncPending = new Map()
let asyncHooked = null

function canCallAsync(bridge, method) {
  return !!(bridge && bridge.callAsync && bridge.asyncResult && /^get/.test(method))
}

function callViaAsync(bridge, method, args) {
  if (asyncHooked !== bridge) {
    asyncHooked = bridge
    bridge.asyncResult.connect((id, payload) => {
      const done = asyncPending.get(id)
      if (done) { asyncPending.delete(id); done(payload) }
    })
  }
  const id = `${method}#${++asyncSeq}`
  return new Promise((resolve) => {
    asyncPending.set(id, resolve)
    bridge.callAsync(method, id, JSON.stringify(args))
  })
}

// A slot that raised answers {"__asyncError": ...}: logged, and null to the
// caller - what the synchronous call gave when its slot raised.
function parseAnswer(method, raw) {
  const out = JSON.parse(raw || 'null')
  if (out && typeof out === 'object' && out.__asyncError) {
    console.error(`[bridge] ${method}: ${out.__asyncError}`)
    return null
  }
  return out
}

/** Call a bridge slot and JSON-parse the string result. */
export async function call(method, arg) {
  const bridge = await getBridge()
  const args = arg === undefined ? [] : [arg]
  const raw = canCallAsync(bridge, method)
    ? await callViaAsync(bridge, method, args)
    : await bridge[method](...args)
  return parseAnswer(method, raw)
}

// The newest call per key wins. An earlier call still running when the same
// view asks again (another day clicked, a filter typed) never settles: its
// .then cannot overwrite the newer answer and its .finally cannot clear the
// loading overlay the newer call is showing. Calls now return out of order -
// they run on a thread pool - so this is needed, not cosmetic.
const latestSeq = new Map()
export function latest(method, arg, key = method) {
  const n = (latestSeq.get(key) || 0) + 1
  latestSeq.set(key, n)
  const settle = (fn) => (value) => (latestSeq.get(key) === n ? fn(value) : new Promise(() => {}))
  return call(method, arg).then(settle((v) => v), settle((e) => Promise.reject(e)))
}
