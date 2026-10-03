// QWebChannel client. Outside PyQt (plain `npm run dev`) it falls back to
// generated data so the dashboard can be worked on in an ordinary browser.

const ACTS = ['visits', 'searches', 'downloads', 'cookies', 'cache']

function mockDays(n) {
  const out = []
  const start = new Date('2026-01-05T00:00:00')
  for (let i = 0; i < n; i++) {
    const d = new Date(start.getTime() + i * 86400000)
    out.push(d.toISOString().slice(0, 10))
  }
  return out
}

function mockBridge() {
  const days = mockDays(60)
  const domains = ['example.test', 'news.test', 'mail.test', 'cdn.test',
    'search.test', 'shop.test', 'ghost.test']

  const heat = {}
  ACTS.forEach((a, ai) => {
    const series = days.map((day, i) => ({
      day,
      value: Math.max(0, Math.round(18 * Math.abs(Math.sin((i + ai * 3) / 5)) - ai)),
    })).filter(d => d.value > 0)
    heat[a] = { days: series, max: series.reduce((m, d) => Math.max(m, d.value), 0) }
  })
  const combined = days.map((day, i) => ({
    day,
    value: ACTS.reduce((s, a) => {
      const hit = heat[a].days.find(d => d.day === day)
      return s + (hit ? hit.value : 0)
    }, 0),
  })).filter(d => d.value > 0)

  const points = []
  domains.slice(0, 6).forEach((domain, di) => {
    ACTS.forEach((activity, ai) => {
      for (let h = 8 + di; h < 20; h += 3 + ai) {
        points.push({ domain, activity, h, hour: `${days[30]}T${String(h).padStart(2, '0')}:00`,
          n: 1 + ((h + di + ai) % 9), browser: di % 2 ? 'Edge' : 'Chrome' })
      }
    })
  })
  const ranges = {}
  points.forEach(p => {
    const r = ranges[p.domain] || (ranges[p.domain] = { min: p.h, max: p.h })
    r.min = Math.min(r.min, p.h); r.max = Math.max(r.max, p.h)
  })

  const J = (o) => Promise.resolve(JSON.stringify(o))

  return {
    getBrowserBounds: () => J({
      hasData: true, minDate: days[0], maxDate: days[days.length - 1],
      sources: { visits: 8421, searches: 96, downloads: 37, cookies: 1723, cache: 45087 },
      browsers: ['Chrome', 'Edge', 'Firefox'],
      profiles: ['Default', 'Profile 1', 'default-release'],
    }),
    getBrowserHeatmaps: () => J({ sources: heat, combined }),
    getBrowserOverview: () => J({
      totals: { events: 55364, domains: 742, activeDays: 58, browsers: 3, profiles: 3 },
      sourceTotals: { visits: 8421, searches: 96, downloads: 37, cookies: 1723, cache: 45087 },
      topDomains: domains.slice(0, 6).map((domain, i) => ({
        domain, visits: 900 - i * 120, typed: 120 - i * 18,
        clicked: 780 - i * 102,
      })),
      intent: {
        terms: [
          { text: 'quarterly report', domain: 'search.test', hits: 12 },
          { text: 'example logi', domain: 'example.test', hits: 9 },
          { text: 'vpn download', domain: 'search.test', hits: 4 },
        ],
        typedUrls: [
          { url: 'https://mail.test/', domain: 'mail.test', title: 'Mail', typed: 31 },
          { url: 'https://example.test/admin', domain: 'example.test', title: 'Admin', typed: 12 },
        ],
      },
      downloads: [
        { started: `${days[40]} 14:10:00`, sourceUrl: 'https://shop.test/setup.exe',
          domain: 'shop.test', targetPath: 'C:\\Users\\a\\Downloads\\setup.exe',
          bytes: 8461234, dangerType: 2, opened: 1, mimeType: 'application/x-msdownload', state: 1 },
        { started: `${days[38]} 09:02:00`, sourceUrl: 'https://cdn.test/report.pdf',
          domain: 'cdn.test', targetPath: 'C:\\Users\\a\\Downloads\\report.pdf',
          bytes: 244118, dangerType: 0, opened: 0, mimeType: 'application/pdf', state: 1 },
      ],
      antiForensics: {
        orphanDomains: [
          { domain: 'ghost.test', sources: ['cookie', 'favicon', 'cache', 'top site'] },
          { domain: 'tracker.test', sources: ['cookie', 'cache'] },
        ],
        orphanCount: 2, visitedDomains: 740,
        profileGap: { profileCreated: '2025-01-01 00:00:00', firstVisit: days[0] },
      },
    }),
    getBrowserDayDetail: (a) => {
      const day = JSON.parse(a || '{}').day || days[30]
      const hourly = Array.from({ length: 24 }, (_, h) =>
        Math.max(0, Math.round(40 * Math.abs(Math.sin(h / 3)))))
      const hourlyBySource = {}
      ACTS.forEach((act, ai) => {
        hourlyBySource[act] = hourly.map(v => Math.max(0, Math.round(v / (ai + 1.5))))
      })
      return J({
        day, hourly, hourlyBySource,
        perSource: Object.fromEntries(ACTS.map(a2 =>
          [a2, hourlyBySource[a2].reduce((s, v) => s + v, 0)])),
        topDomains: domains.slice(0, 6).map((domain, i) => ({
          domain, total: 200 - i * 25,
          counts: Object.fromEntries(ACTS.map((a2, ai) => [a2, Math.max(1, 40 - i * 4 - ai * 6)])),
        })),
        events: Array.from({ length: 60 }, (_, i) => {
          const h = String(6 + (i % 16)).padStart(2, '0')
          const m = String((i * 7) % 60).padStart(2, '0')
          const domain = domains[i % domains.length]
          return {
            t: `${day} ${h}:${m}:00`, time: `${h}:${m}:00`,
            activity: ACTS[i % ACTS.length], domain,
            label: `Sample page ${i + 1}`, url: `https://${domain}/page/${i + 1}`,
            browser: ['Chrome', 'Edge', 'Firefox'][i % 3], profile: 'Default',
          }
        }),
        eventsTotal: hourly.reduce((s, v) => s + v, 0),
      })
    },
    getBrowserDayActivity: (a) => {
      const day = JSON.parse(a || '{}').day || days[30]
      return J({ day, domains: domains.slice(0, 6), points, ranges })
    },
    getBrowserDomainDetail: (a) => {
      const domain = JSON.parse(a || '{}').domain || domains[0]
      return J({
        domain, hasData: true, visitCount: 412,
        visits: Array.from({ length: 12 }, (_, i) => ({
          time: `${days[30 - (i % 5)]} ${String(9 + i).padStart(2, '0')}:1${i}:00`,
          url: `https://${domain}/page/${i}`, title: `Page ${i}`,
          transition: i % 3 === 0 ? 'typed' : 'link', typed: i % 3 === 0 ? 1 : 0,
        })),
        cookies: [
          { host: `.${domain}`, name: 'sid', created: `${days[10]} 08:00:00`,
            lastAccess: `${days[44]} 19:22:00`, expires: '2027-01-01 00:00:00',
            secure: 1, httpOnly: 1 },
        ],
        cache: [
          { url: `https://${domain}/app.js`, fetched: `${days[44]} 19:22:03`, status: 200,
            contentType: 'text/javascript', bytes: 148221, encoding: 'br', format: 'blockfile' },
          { url: `https://${domain}/logo.png`, fetched: `${days[44]} 19:22:04`, status: 304,
            contentType: 'image/png', bytes: 0, encoding: '', format: 'blockfile' },
        ],
        credentials: [
          { origin: `https://${domain}/login`, hasUsername: true, created: `${days[2]} 10:00:00`,
            lastUsed: `${days[44]} 19:21:00`, timesUsed: 23, scheme: 'v20', blacklisted: 0 },
        ],
        downloads: [],
      })
    },
  }
}

let bridgePromise = null

export function getBridge() {
  if (bridgePromise) return bridgePromise
  bridgePromise = new Promise((resolve) => {
    if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {
      new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
        resolve(channel.objects.bridge)
      })
    } else {
      console.warn('[browser-viz] QWebChannel not available - using mock data')
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
