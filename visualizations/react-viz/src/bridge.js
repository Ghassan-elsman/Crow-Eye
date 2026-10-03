/**
 * QWebChannel bridge to the Python VizBridge.
 *
 * Mirrors eye/ui/react/src/bridge.ts: waits for qt.webChannelTransport, builds
 * the channel and resolves with `channel.objects.bridge`. In a plain browser
 * (no Qt) it resolves with a mock so the UI can be developed standalone.
 */

let bridgePromise = null

function mockBridge() {
  // Deterministic sample data for standalone/browser development.
  const days = []
  const today = new Date()
  for (let i = 59; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(d.getDate() - i)
    const day = d.toISOString().slice(0, 10)
    const base = Math.max(0, Math.round(2000 * Math.abs(Math.sin(i / 5)) + (Math.random() * 800 - 200)))
    days.push({
      day, value: base, execWindows: base, execApps: 40 + (i % 120),
      netBytes: base * 1e6, presenceSecs: Math.round(base * 20), topApp: 'svchost.exe',
    })
  }
  return {
    getSrumBounds: () => Promise.resolve(JSON.stringify({
      hasData: true, minDate: days[0].day, maxDate: days[days.length - 1].day,
      providers: { application_usage: 1, network_data: 1, network_connectivity: 1, energy: 1, app_timeline: 1 },
    })),
    getSrumHeatmaps: () => {
      const keys = ['application_usage', 'network_data', 'network_connectivity', 'energy', 'app_timeline']
      const providers = {}; const combinedMap = {}
      keys.forEach((k, ki) => {
        const dd = days.map(d => ({ day: d.day, value: Math.round(d.value * (0.25 + (ki + 1) * 0.14) * (0.5 + Math.random())) }))
        providers[k] = { days: dd, max: Math.max(1, ...dd.map(x => x.value)) }
        dd.forEach(x => { combinedMap[x.day] = (combinedMap[x.day] || 0) + x.value })
      })
      const combined = Object.entries(combinedMap).map(([day, value]) => ({ day, value })).sort((a, b) => a.day < b.day ? -1 : 1)
      return Promise.resolve(JSON.stringify({ providers, combined }))
    },
    getSrumDayDetail: (argsJson) => {
      const a = JSON.parse(argsJson || '{}')
      const keys = ['application_usage', 'network_data', 'network_connectivity', 'energy', 'app_timeline']
      const hourly = Array.from({ length: 24 }, (_, h) => Math.round(200 * Math.abs(Math.sin(h / 3))))
      const hourlyByProvider = {}
      keys.forEach((k, ki) => { hourlyByProvider[k] = Array.from({ length: 24 }, (_, h) => Math.round(90 * Math.abs(Math.sin((h + ki) / 3)))) })
      const topAppsByProvider = ['svchost.exe', 'chrome.exe', 'edge.exe', 'System', 'Teams.exe', 'powershell.exe'].map(app => {
        const counts = Object.fromEntries(keys.map((k, ki) => [k, Math.round(Math.random() * 200 * (ki === 0 ? 3 : 1))]))
        return { app, total: Object.values(counts).reduce((x, y) => x + y, 0), counts }
      })
      return Promise.resolve(JSON.stringify({
        day: a.day, hourly, hourlyByProvider, topAppsByProvider,
        topApps: [{ app: 'svchost.exe', windows: 737, cycles: 1e9 }, { app: 'chrome.exe', windows: 120, cycles: 5e8 }],
        perProvider: { application_usage: 4728, network_data: 910, network_connectivity: 120, energy: 57, app_timeline: 320 },
        presence: { keyboard: 240, mouse: 120, focus: 3600 },
      }))
    },
    getSrumDayActivity: (argsJson) => {
      const a = JSON.parse(argsJson || '{}')
      const apps = ['svchost.exe', 'chrome.exe', 'edge.exe', 'System', 'WhatsApp.exe', 'nvcontainer.exe', 'powershell.exe', 'Teams.exe']
      const usersL = ['PC\\Ann', 'PC\\Bob', 'NT AUTHORITY\\SYSTEM', 'NT AUTHORITY\\NETWORK SERVICE']
      const points = []; const ranges = {}
      for (let ai = 0; ai < apps.length; ai++) {
        for (let h = 0; h < 24; h++) {
          if (Math.random() < 0.55) continue
          const u = usersL[(ai + h) % usersL.length]
          points.push({ app: apps[ai], user: u, userSid: 'S', h, hour: `${a.day}T${String(h).padStart(2, '0')}:00`,
            bytesSent: Math.round(Math.random() * 5e7 * (ai % 3 === 0 ? 4 : 1)),
            bytesReceived: Math.round(Math.random() * 9e7),
            cpu: Math.round(Math.random() * 5e9), disk: Math.round(Math.random() * 2e7),
            battery: 60 + Math.round(Math.random() * 40), focusS: Math.round(Math.random() * 3000), keyboardS: Math.round(Math.random() * 600) })
          const r = ranges[apps[ai]] || (ranges[apps[ai]] = { min: h, max: h })
          if (h < r.min) r.min = h; if (h > r.max) r.max = h
        }
      }
      return Promise.resolve(JSON.stringify({ day: a.day, apps, users: usersL, points, ranges }))
    },
    getSrumOverview: () => {
      const keys = ['application_usage', 'network_data', 'network_connectivity', 'energy', 'app_timeline']
      const counts = (scale) => Object.fromEntries(keys.map((k, ki) => [k, Math.round(scale * (ki === 0 ? 4 : 1) * (0.4 + Math.random()))]))
      const networkByDay = days.map(d => ({ day: d.day, sent: Math.round(d.value * 1.2e6 * (0.5 + Math.random())), received: Math.round(d.value * 2.4e6 * (0.5 + Math.random())) }))
      const topNetworkApps = ['chrome.exe', 'edge.exe', 'svchost.exe', 'Teams.exe', 'WhatsApp.exe', 'OneDrive.exe']
        .map((app, i) => ({ app, sent: Math.round((6 - i) * 5e8 * (0.5 + Math.random())), received: Math.round((6 - i) * 1.1e9 * (0.5 + Math.random())) }))
      return Promise.resolve(JSON.stringify({
        totals: { bytesSent: 4.2e9, bytesReceived: 8.9e9, cpu: 5.6e14, disk: 3.1e9, presenceSecs: 176400, apps: 214, activeDays: 58 },
        topApps: ['svchost.exe', 'chrome.exe', 'System', 'Teams.exe', 'edge.exe', 'WhatsApp.exe'].map((app, i) => ({ app, total: 0, counts: counts(3000 - i * 400) })),
        byUser: [{ user: 'PC\\Ann' }, { user: 'NT AUTHORITY\\SYSTEM' }, { user: 'PC\\Bob' }].map((u, i) => ({ ...u, counts: counts(4000 - i * 900) })),
        providerTotals: { application_usage: 220563, network_data: 52265, network_connectivity: 5319, energy: 2766, app_timeline: 50374 },
        networkByDay, topNetworkApps,
      }))
    },
    getSrumAppDetail: (argsJson) => {
      const a = JSON.parse(argsJson || '{}')
      const hourly = Array.from({ length: 18 }, (_, i) => ({
        hour: new Date(Date.now() - (17 - i) * 3600000).toISOString().slice(0, 13) + ':00',
        bytesSent: Math.round(Math.random() * 5e6), bytesReceived: Math.round(Math.random() * 9e6),
        cpu: Math.round(Math.random() * 5e8), disk: Math.round(Math.random() * 2e6),
        battery: 60 + Math.round(Math.random() * 40), focusS: Math.round(Math.random() * 500), keyboardS: 0,
      }))
      return Promise.resolve(JSON.stringify({
        app: a.app, hourly,
        byUser: [{ user: 'PC\\Ann', hours: 12, cpu: 4e9, bytes: 8e7 }, { user: 'PC\\Bob', hours: 6, cpu: 1e9, bytes: 2e7 }],
        totals: { bytesSent: 4e7, bytesReceived: 9e7, cpu: 5e9, disk: 2e7, focusS: 5000, keyboardS: 900, hours: 18, first: hourly[0].hour, last: hourly.at(-1).hour },
        radar: { cpu: 42, disk: 20, netOut: 15, netIn: 30, presence: 8 },
      }))
    },
    _mock: true,
  }
}

export function getBridge() {
  if (bridgePromise) return bridgePromise
  bridgePromise = new Promise((resolve) => {
    if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {
      new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
        resolve(channel.objects.bridge)
      })
    } else {
      console.warn('[viz] QWebChannel not available - using mock data')
      resolve(mockBridge())
    }
  })
  return bridgePromise
}

/** Call a bridge slot and JSON-parse the string result. */
export async function call(method, arg) {
  const bridge = await getBridge()
  const raw = arg === undefined ? await bridge[method]() : await bridge[method](arg)
  return JSON.parse(raw || 'null')
}
