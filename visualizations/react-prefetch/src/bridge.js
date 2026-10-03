/** QWebChannel bridge to the Python PrefetchBridge (+ standalone mock). */
let bridgePromise = null

function mockBridge() {
  const LOC = ['system', 'programfiles', 'usertemp', 'removable', 'other']
  const days = []
  const start = new Date('2026-01-20')
  for (let i = 0; i < 28; i++) { const d = new Date(start); d.setDate(d.getDate() + i); days.push(d.toISOString().slice(0, 10)) }
  const sources = {}; const combined = {}
  LOC.forEach((l, li) => {
    const dd = days.filter((_, i) => (i * (li + 1)) % 2 === 0).map(day => ({ day, value: Math.max(0, Math.round((li === 0 ? 30 : 8) * Math.random())) })).filter(x => x.value > 0)
    sources[l] = { days: dd, max: Math.max(1, ...dd.map(x => x.value)) }
    dd.forEach(x => { combined[x.day] = (combined[x.day] || 0) + x.value })
  })
  const exes = ['SVCHOST.EXE', 'CHROME.EXE', 'GIT.EXE', 'POWERSHELL.EXE', 'SETUP.EXE', 'MALWARE.EXE']
  const mkEvents = (n) => Array.from({ length: n }, (_, i) => ({
    exe: exes[i % exes.length], t: `2026-02-16 ${String(i % 24).padStart(2, '0')}:${String(i % 60).padStart(2, '0')}:00`,
    hour: i % 24, location: LOC[i % LOC.length], runCount: 1 + (i % 8),
    volume: i % 5 === 3 ? 'KINGSTON' : 'OS', path: `C:\\path\\${exes[i % exes.length]}`, filename: `${exes[i % exes.length]}-${i}.pf`,
  }))
  const byHour = Object.fromEntries(LOC.map((l, li) => [l, Array.from({ length: 24 }, (_, h) => Math.round(4 * Math.abs(Math.sin((h + li) / 3)) * Math.random()))]))
  const topPrograms = exes.map((e, i) => ({ exe: e, runCount: 8 - i, location: LOC[i % LOC.length], lastExecuted: '2026-02-16 10:00:00', filename: `${e}-${i}.pf`, volume: 'OS' }))

  return {
    getPrefetchBounds: () => Promise.resolve(JSON.stringify({
      hasData: true, minDate: days[0], maxDate: days[days.length - 1],
      counts: { system: 168, programfiles: 131, usertemp: 57, removable: 3, other: 23 }, volumes: ['OS', 'KINGSTON'],
    })),
    getPrefetchTimeline: () => Promise.resolve(JSON.stringify({
      sources, combined: Object.entries(combined).map(([day, value]) => ({ day, value })).sort((a, b) => a.day < b.day ? -1 : 1),
    })),
    getPrefetchOverview: () => Promise.resolve(JSON.stringify({
      totals: { programs: 382, runs: 1561, activeDays: 12, userTemp: 57, removable: 3, singleRun: 154 },
      byLocation: [{ loc: 'system', n: 168 }, { loc: 'programfiles', n: 131 }, { loc: 'usertemp', n: 57 }, { loc: 'removable', n: 3 }, { loc: 'other', n: 23 }],
      topPrograms,
      volumes: [{ label: 'OS', serial: '786BC91D', type: 'fixed', n: 375 }, { label: 'KINGSTON', serial: 'A1B2C3', type: 'removable', n: 3 }],
      insights: { userTemp: 57, removable: 3, singleRun: 154, maxRuns: 8 },
    })),
    getPrefetchDayDetail: () => Promise.resolve(JSON.stringify({ events: mkEvents(40), byHour, byProgram: topPrograms.map(p => ({ exe: p.exe, n: p.runCount })), topDirs: [{ dir: 'C:\\Windows\\System32', n: 40 }, { dir: 'C:\\Program Files', n: 22 }] })),
    getPrefetchProgramDetail: () => Promise.resolve(JSON.stringify({
      exe: 'GIT.EXE', exePath: 'C:\\Program Files\\Git\\cmd\\GIT.EXE', hash: '1A2B3C4D', runCount: 8, location: 'programfiles',
      runTimes: ['2026-02-10 08:00:00', '2026-02-12 09:00:00', '2026-02-14 10:00:00', '2026-02-16 11:00:00'],
      volume: { label: 'OS', serial: '786BC91D', removable: false },
      pf: { created: '2026-02-10 08:00:01', modified: '2026-02-16 11:00:01', accessed: '2026-02-16 12:00:00' },
      resources: [
        { path: 'C:\\Windows\\System32\\NTDLL.DLL', unusual: false },
        { path: 'C:\\Program Files\\Git\\cmd\\GIT.EXE', unusual: false },
        { path: 'C:\\Users\\Ann\\AppData\\Local\\Temp\\inject.dll', unusual: true },
      ],
      directories: ['C:\\Windows\\System32', 'C:\\Program Files\\Git'],
      unusualCount: 1,
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
      console.warn('[prefetch] QWebChannel not available - using mock data')
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
