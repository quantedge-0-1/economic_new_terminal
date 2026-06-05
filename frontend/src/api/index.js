const BASE = '/api/v1'

async function get(path, params = {}) {
  const url = new URL(BASE + path, window.location.origin)
  Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v))
  const res = await fetch(url)
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`)
  return res.json()
}

async function post(path, body = {}) {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`)
  return res.json()
}

export const api = {
  // Calendar
  getUpcoming:      (params) => get('/calendar/upcoming', params),
  getRecent:        (params) => get('/calendar/recent', params),
  getJustReleased:  (params) => get('/calendar/just-released', params),
  refreshCalendar:  () => post('/calendar/refresh'),

  // AI Analysis
  analyzeEvent: (data) => post('/analysis/event', data),
  getAnalysisHistory: () => get('/analysis/history'),

  // Prices
  getLivePrices: () => get('/prices/live'),

  // Surprise
  computeSurprise: (data) => post('/surprise/compute', data),
  getRecentSurprises: (params) => get('/surprise/recent', params),

  // News
  getLatestNews: (params) => get('/news/latest', params),
  refreshNews: () => post('/news/refresh'),

  // Alerts
  getAlerts: (params) => get('/alerts/', params),
  markAlertRead: (id) => fetch(`${BASE}/alerts/${id}/read`, { method: 'PATCH' }),

  // Institutional Sentiment Engine (ISS)
  analyzeSentiment: (data)  => post('/sentiment/analyze', data),
  getCurrentSentiment: ()   => get('/sentiment/current'),
  getMcs: (sentiment)       => get('/sentiment/mcs', { sentiment }),

  // Event Memory Engine
  getEventMemory:    (params) => get('/sentiment/event-memory', params),
  getMemoryPatterns: ()       => get('/sentiment/event-memory/patterns'),
  triggerMemoryFill: ()       => post('/sentiment/event-memory/fill'),

  // Pre-Release Scanner
  getPreReleaseStatus: () => get('/pre-release/status'),

  // Health
  health: () => fetch('/health').then(r => r.json()),
}
