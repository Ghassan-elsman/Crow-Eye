/**
 * QWebChannel bridge to the Python MftUsnBridge. Same shape as the SRUM app's
 * bridge: wait for qt.webChannelTransport, resolve with channel.objects.bridge;
 * in a plain browser resolve with a mock so the UI runs standalone.
 */
let bridgePromise = null

function mockBridge() {
  const CATS = ['create', 'delete', 'rename', 'data', 'meta']
  const pad = (n) => String(n).padStart(2, '0')

  // A short USN window (one day, hour buckets) + a long MFT history.
  const day = '2026-02-16'
  const usnEvents = {}
  const combined = {}
  CATS.forEach((c, ci) => {
    const buckets = []
    for (let h = 0; h < 24; h++) {
      const key = `${day}T${pad(h)}:00`
      const v = Math.max(0, Math.round((ci === 4 ? 300 : 90) * Math.abs(Math.sin((h + ci) / 3)) * (0.4 + Math.random())))
      buckets.push({ key, value: v })
      combined[key] = (combined[key] || 0) + v
    }
    usnEvents[c] = { buckets, max: Math.max(1, ...buckets.map(b => b.value)) }
  })
  const mftHistory = []
  const start = new Date('2024-01-01')
  for (let i = 0; i < 400; i++) {
    const d = new Date(start); d.setDate(d.getDate() + i)
    const iso = d.toISOString().slice(0, 10)
    mftHistory.push({ day: iso, created: Math.round(200 * Math.abs(Math.sin(i / 9)) * Math.random()),
      modified: Math.round(340 * Math.abs(Math.cos(i / 7)) * Math.random()) })
  }

  const dirsMock = ['Windows/System32', 'Users/Ann/Documents', 'Program Files/App', 'Windows/Temp', '$Extend/$Deleted', 'Users/Ann/Downloads']
  const extsMock = ['dll', 'exe', 'log', 'tmp', 'png', 'txt', '(none)']
  const reasonsMock = ['DATA_EXTEND | FILE_CREATE | CLOSE', 'RENAME_NEW_NAME | CLOSE', 'SECURITY_CHANGE | CLOSE',
    'DATA_OVERWRITE | CLOSE', 'FILE_DELETE | CLOSE', 'BASIC_INFO_CHANGE | CLOSE']
  const catsOf = (r) => {
    const s = []
    if (r.includes('FILE_CREATE')) s.push('create')
    if (r.includes('FILE_DELETE')) s.push('delete')
    if (r.includes('RENAME')) s.push('rename')
    if (/DATA_(OVERWRITE|EXTEND|TRUNCATION)/.test(r)) s.push('data')
    if (/(BASIC_INFO|SECURITY|OBJECT_ID|INDEXABLE)/.test(r)) s.push('meta')
    return s
  }

  const mockEvents = (n) => {
    const evs = []
    for (let i = 0; i < n; i++) {
      const r = reasonsMock[i % reasonsMock.length]
      const dir = dirsMock[i % dirsMock.length]
      const ext = extsMock[i % extsMock.length]
      const h = i % 24
      evs.push({ rec: 1000 + i, path: `./${dir}/file${i}.${ext}`, fn: `file${i}.${ext}`,
        t: `${day}T${pad(h)}:${pad(i % 60)}:00+00:00`, hour: h, cats: catsOf(r),
        size: Math.round(Math.random() * 5e6), deleted: 0 })
    }
    return evs
  }
  const byHour = Object.fromEntries(CATS.map((c, ci) => [c, Array.from({ length: 24 }, (_, h) => Math.round(60 * Math.abs(Math.sin((h + ci) / 3)) * Math.random()))]))
  const topDirs = dirsMock.map((d, i) => ({ dir: d, n: 900 - i * 120 }))
  const topExts = extsMock.map((e, i) => ({ ext: e, n: 800 - i * 90 }))

  return {
    getMftUsnBounds: () => Promise.resolve(JSON.stringify({
      hasData: true, mftMin: '2024-01-01', mftMax: '2026-02-16', usnMin: day, usnMax: day,
      volumes: ['C:', 'D:'], hasVolume: true, hasAds: true,
    })),
    getMftUsnTimelines: () => Promise.resolve(JSON.stringify({
      mftHistory, usnEvents,
      combined: Object.entries(combined).map(([key, value]) => ({ key, value })).sort((a, b) => a.key < b.key ? -1 : 1),
      bucket: 'hour',
    })),
    getMftUsnOverview: () => Promise.resolve(JSON.stringify({
      totals: { files: 587975, directories: 133707, withEvents: 10088, deleted: 12, ads: 340,
        created: 1168, renamed: 833, dataChanged: 1803, deletedEvents: 23 },
      anomalies: { timestompCandidates: 421, usnGaps: 3, deletedButPresent: 12, ads: 340 },
      byCategory: { create: 1168, delete: 23, rename: 833, data: 1803, meta: 7150 },
      topDirs, topExts,
    })),
    getMftUsnWindowDetail: (argsJson) => {
      const a = JSON.parse(argsJson || '{}')
      return Promise.resolve(JSON.stringify({ events: mockEvents(220), byHour, topDirs, topExts, bucket: a.bucket }))
    },
    getMftUsnFileDetail: (argsJson) => {
      const a = JSON.parse(argsJson || '{}')
      return Promise.resolve(JSON.stringify({
        rec: JSON.parse(argsJson || '{}').rec || 1000, path: './Users/Ann/Documents/report.docx', filename: 'report.docx',
        isDir: 0, deleted: 0, size: 284219,
        si: { created: '2026-02-10T08:11:04+00:00', modified: '2026-02-16T05:20:00+00:00', accessed: '2026-02-16T05:20:00+00:00', mftChanged: '2026-02-16T05:20:00+00:00' },
        fnTimes: { created: '2026-02-10T08:11:04+00:00', modified: '2026-02-14T09:02:00+00:00', accessed: '2026-02-16T05:20:00+00:00', mftChanged: '2026-02-16T05:20:00+00:00' },
        events: [
          { t: '2026-02-10T08:11:04+00:00', cats: ['create'], reason: 'DATA_EXTEND | FILE_CREATE | CLOSE' },
          { t: '2026-02-14T09:02:00+00:00', cats: ['data'], reason: 'DATA_OVERWRITE | CLOSE' },
          { t: '2026-02-16T05:20:00+00:00', cats: ['meta'], reason: 'SECURITY_CHANGE | CLOSE' },
        ],
        flags: ['SI vs FN creation differ'],
      }))
    },
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

export async function call(method, arg) {
  const bridge = await getBridge()
  const raw = arg === undefined ? await bridge[method]() : await bridge[method](arg)
  return JSON.parse(raw || 'null')
}
