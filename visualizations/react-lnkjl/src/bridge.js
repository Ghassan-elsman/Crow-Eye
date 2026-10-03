/** QWebChannel bridge to the Python LnkJlBridge (+ standalone mock). */
let bridgePromise = null

function mockBridge() {
  const SRC = ['lnk', 'auto', 'custom']
  const days = []
  const start = new Date('2025-11-01')
  for (let i = 0; i < 90; i++) { const d = new Date(start); d.setDate(d.getDate() + i); days.push(d.toISOString().slice(0, 10)) }
  const sources = {}; const combined = {}
  SRC.forEach((s, si) => {
    const dd = days.filter((_, i) => (i * (si + 2)) % 3 === 0).map(day => ({ day, value: Math.max(0, Math.round((si === 0 ? 8 : 3) * Math.random())) })).filter(x => x.value > 0)
    sources[s] = { days: dd, max: Math.max(1, ...dd.map(x => x.value)) }
    dd.forEach(x => { combined[x.day] = (combined[x.day] || 0) + x.value })
  })
  const apps = ['Windows Explorer', 'Microsoft Word', 'WezTerm', 'Notepad++', 'VLC']
  const dirs = ['C:\\Users\\Ann\\Documents', 'C:\\Users\\Ann\\Downloads', 'C:\\Windows\\System32', 'E:\\', 'C:\\Users\\Ann\\AppData\\Local\\Temp']
  const exts = ['docx', 'exe', 'pdf', 'png', 'md', '(none)']
  const mkEvents = (n) => Array.from({ length: n }, (_, i) => ({
    source: SRC[i % 3], app: i % 3 === 0 ? '' : apps[i % apps.length],
    target: `${dirs[i % dirs.length]}\\file${i}.${exts[i % exts.length]}`, name: `file${i}.${exts[i % exts.length]}`,
    t: `2026-02-15 ${String(i % 24).padStart(2, '0')}:${String(i % 60).padStart(2, '0')}:00`, hour: i % 24,
    volume: i % 4 === 0 ? 'HIKVISION' : 'OS', driveType: i % 4 === 0 ? 'DRIVE_REMOVABLE' : 'DRIVE_FIXED',
  }))
  const byHour = Object.fromEntries(SRC.map((s, si) => [s, Array.from({ length: 24 }, (_, h) => Math.round(3 * Math.abs(Math.sin((h + si) / 3)) * Math.random()))]))
  const topDirs = dirs.map((d, i) => ({ dir: d, n: 60 - i * 9 }))
  const topExts = exts.map((e, i) => ({ ext: e, n: 55 - i * 8 }))
  const byApp = apps.map((a, i) => ({ app: a, n: 22 - i * 4 }))

  return {
    getLnkBounds: () => Promise.resolve(JSON.stringify({
      hasData: true, minDate: days[0], maxDate: days[days.length - 1],
      counts: { lnk: 191, auto: 23, custom: 19 }, volumes: ['OS', 'HIKVISION'], hasApp: true,
    })),
    getLnkTimeline: () => Promise.resolve(JSON.stringify({
      sources, combined: Object.entries(combined).map(([day, value]) => ({ day, value })).sort((a, b) => a.day < b.day ? -1 : 1),
    })),
    getLnkOverview: () => Promise.resolve(JSON.stringify({
      totals: { records: 233, targets: 80, lnk: 191, auto: 23, custom: 19 },
      byApp, topDirs, topExts,
      volumes: [
        { driveType: 'DRIVE_FIXED', label: 'OS', serial: '786BC91D', n: 190 },
        { driveType: 'DRIVE_REMOVABLE', label: 'HIKVISION', serial: 'DD366F', n: 14 },
        { driveType: 'DRIVE_FIXED', label: '', serial: '2CCD8021', n: 8 },
      ],
      insights: { removable: 14, network: 2, tempDownloads: 9, externalVolumes: 1 },
    })),
    getLnkDayDetail: (a) => Promise.resolve(JSON.stringify({ events: mkEvents(40), byHour, byApp, topDirs, topExts })),
    getLnkTargetDetail: (a) => Promise.resolve(JSON.stringify({
      target: 'C:\\Users\\Ann\\Documents\\report.docx', name: 'report.docx', ext: 'docx', dir: 'C:\\Users\\Ann\\Documents',
      sources: ['lnk', 'auto'],
      mace: { accessed: '2026-02-16 05:20:00', created: '2026-02-10 08:11:04', modified: '2026-02-14 09:02:00' },
      volume: { type: 'DRIVE_FIXED', label: 'OS', serial: '786BC91D' },
      mftEntry: '84213', tracker: '00:1a:2b:3c:4d:5e', knownFolder: '', args: '',
      refs: [
        { source: 'lnk', app: '', sourceName: 'report.lnk', tAccess: '2026-02-16 05:20:00', tCreation: '2026-02-10 08:11:04', tModification: '2026-02-14 09:02:00', volume: 'OS', driveType: 'DRIVE_FIXED', serial: '786BC91D' },
        { source: 'auto', app: 'Microsoft Word', sourceName: 'a1b2.automaticDestinations-ms', tAccess: '2026-02-16 05:19:00', tCreation: '2026-02-10 08:11:04', tModification: '2026-02-14 09:02:00', volume: 'OS', driveType: 'DRIVE_FIXED', serial: '786BC91D' },
      ],
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
      console.warn('[lnkjl] QWebChannel not available - using mock data')
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
