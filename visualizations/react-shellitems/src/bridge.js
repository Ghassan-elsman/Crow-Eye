/** QWebChannel bridge to the Python ShellItemsBridge (+ standalone mock). */
let bridgePromise = null

function mockBridge() {
  const SRC = ['shellbags', 'recentdocs', 'opensave', 'lastvisited', 'typedpaths', 'runmru', 'search']
  const days = []
  const start = new Date('2026-01-24')
  for (let i = 0; i < 24; i++) { const d = new Date(start); d.setDate(d.getDate() + i); days.push(d.toISOString().slice(0, 10)) }
  const sources = {}; const combined = {}
  SRC.forEach((s, si) => {
    const dd = days.filter((_, i) => (i * (si + 2)) % 3 !== 1).map(day => ({ day, value: Math.max(0, Math.round((si === 0 ? 22 : 6) * Math.random())) })).filter(x => x.value > 0)
    sources[s] = { days: dd, max: Math.max(1, ...dd.map(x => x.value)) }
    dd.forEach(x => { combined[x.day] = (combined[x.day] || 0) + x.value })
  })
  const places = ['C:\\Users\\Ann\\Documents', 'C:\\Users\\Ann\\Downloads', 'D:\\Evidence', '\\\\NAS\\share\\loot', 'C:\\Windows\\System32', 'C:\\Users\\Ann\\Desktop']
  const targets = ['report.docx', 'passwords.xlsx', 'setup.exe', 'photos', 'invoice.pdf', 'notes.txt']
  const mkEvents = (n) => Array.from({ length: n }, (_, i) => ({
    id: i, source: SRC[i % SRC.length], target: targets[i % targets.length],
    t: `2026-02-08 ${String(i % 24).padStart(2, '0')}:${String((i * 7) % 60).padStart(2, '0')}:00`,
    hour: i % 24, itemType: ['folder', 'file', 'command', 'search'][i % 4],
    mru: i % 9, volume: i % 5 === 2 ? 'D:' : (i % 7 === 4 ? '\\\\NAS\\share' : 'C:'),
    path: places[i % places.length] + '\\' + targets[i % targets.length],
  }))
  const byHour = Object.fromEntries(SRC.map((s, si) => [s, Array.from({ length: 24 }, (_, h) => Math.round(3 * Math.abs(Math.sin((h + si) / 3)) * Math.random()))]))

  return {
    getShellItemsBounds: () => Promise.resolve(JSON.stringify({
      hasData: true, minDate: days[0], maxDate: days[days.length - 1],
      counts: { shellbags: 412, recentdocs: 96, opensave: 44, lastvisited: 18, typedpaths: 11, runmru: 7, search: 5 },
      volumes: ['C:', 'D:', '\\\\NAS\\share'],
    })),
    getShellItemsTimeline: () => Promise.resolve(JSON.stringify({
      sources, combined: Object.entries(combined).map(([day, value]) => ({ day, value })).sort((a, b) => a.day < b.day ? -1 : 1),
    })),
    getShellItemsOverview: () => Promise.resolve(JSON.stringify({
      totals: { items: 593, targets: 421, sources: 7, activeDays: 19, network: 12, removable: 28, users: 2 },
      bySource: [
        { source: 'shellbags', n: 412 }, { source: 'recentdocs', n: 96 }, { source: 'opensave', n: 44 },
        { source: 'lastvisited', n: 18 }, { source: 'typedpaths', n: 11 }, { source: 'runmru', n: 7 }, { source: 'search', n: 5 },
      ],
      topPlaces: places.map((p, i) => ({ place: p, n: 40 - i * 5 })),
      topFiles: targets.map((f, i) => ({ file: f, n: 18 - i * 2 })),
      volumes: [
        { label: 'C:', type: 'fixed', n: 520 }, { label: 'D:', type: 'removable', n: 28 }, { label: '\\\\NAS\\share', type: 'network', n: 12 },
      ],
      insights: { network: 12, removable: 28, users: 2, macMismatch: 3 },
    })),
    getShellItemsDayDetail: () => Promise.resolve(JSON.stringify({
      events: mkEvents(36), byHour,
      bySource: SRC.map(s => ({ source: s, n: 2 + (s.length % 5) })),
      topPlaces: places.map((p, i) => ({ place: p, n: 12 - i })),
    })),
    getShellItemsDayActivity: () => {
      const ev = mkEvents(36)
      const items = [...new Set(ev.map(e => e.target))]
      const points = ev.map(e => ({ item: e.target, hour: e.hour, value: 1 + (e.hour % 4), source: e.source }))
      const ranges = {}
      points.forEach(p => { const r = ranges[p.item]; ranges[p.item] = r ? { min: Math.min(r.min, p.hour), max: Math.max(r.max, p.hour) } : { min: p.hour, max: p.hour } })
      return Promise.resolve(JSON.stringify({ day: '2026-02-08', items, points, ranges }))
    },
    getShellItemsFocus: () => Promise.resolve(JSON.stringify({ source: '' })),
    getShellItemsAll: (a) => {
      const args = JSON.parse(a || '{}')
      const srcs = ['shellbags', 'opensave', 'lastvisited', 'typedpaths', 'dialogapps']
      const all = Array.from({ length: 1178 }, (_, i) => ({
        id: i, t: `2026-${String(9 - (i % 8)).padStart(2, '0')}-${String(27 - (i % 27)).padStart(2, '0')} 1${i % 10}:0${i % 6}:00`,
        source: srcs[i % srcs.length], target: ['Pictures', 'Downloads', 'loot', 'report.docx', 'brave.exe'][i % 5],
        path: i % 5 === 4 ? '' : `C:\\Users\\Ann\\Item${i}`, user: 'CROW-PC\\Ann', itemType: ['folder', 'folder', 'network', 'file', 'application'][i % 5], volume: 'C:',
      }))
      const off = args.offset || 0
      return Promise.resolve(JSON.stringify({ total: all.length, days: 125, offset: off, rows: all.slice(off, off + (args.limit || 500)) }))
    },
    getShellItemsItemDetail: () => Promise.resolve(JSON.stringify({
      source: 'shellbags', target: 'loot', path: '\\\\NAS\\share\\loot', itemType: 'network',
      volume: '\\\\NAS\\share', volType: 'network', location: 'network', mruPosition: 0,
      when: '2026-02-08 21:14:03', user: 'Ann', note: '',
      times: { created: '2026-02-01 09:00:00', modified: '2026-02-08 21:14:03', accessed: '2026-02-08 21:14:03', lastWritten: '2026-02-09 02:00:00', keyLastWrite: '2026-02-09 02:00:00' },
      mftRecord: '', size: '', registryPath: 'HKU\\...\\BagMRU\\3\\1', parentPath: '\\\\NAS\\share',
      macMismatch: true,
    })),
    _mock: true,
  }
}

export function getBridge() {
  if (bridgePromise) return bridgePromise
  bridgePromise = new Promise((resolve) => {
    if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {
      new window.QWebChannel(window.qt.webChannelTransport, (channel) => resolve(channel.objects.bridge))
    } else {
      console.warn('[shellitems] QWebChannel not available - using mock data')
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
