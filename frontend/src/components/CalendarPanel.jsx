import { useState, useEffect, useRef } from 'react'
import { api } from '../api/index.js'
import { useInterval } from '../hooks/useInterval.js'

const IMPORTANCE_COLOR = { high: 'var(--red)', medium: 'var(--amber)', low: 'var(--text-muted)' }
const IMPORTANCE_DOTS = { high: '●●●', medium: '●●○', low: '●○○' }

function ImportanceBadge({ level }) {
  const color = IMPORTANCE_COLOR[level] || 'var(--text-muted)'
  return <span style={{ color, fontSize: 10 }}>{IMPORTANCE_DOTS[level] || '?'}</span>
}

function SurpriseBadge({ label }) {
  if (!label) return null
  const map = {
    large_beat: { cls: 'badge-green', text: '▲▲ LARGE BEAT' },
    beat:       { cls: 'badge-green', text: '▲ BEAT' },
    in_line:    { cls: 'badge-blue',  text: '→ IN LINE' },
    miss:       { cls: 'badge-red',   text: '▼ MISS' },
    large_miss: { cls: 'badge-red',   text: '▼▼ LARGE MISS' },
  }
  const b = map[label]
  if (!b) return null
  return <span className={`badge ${b.cls}`}>{b.text}</span>
}

function inferSurpriseLabel(event) {
  if (event.actual == null || event.forecast == null || event.forecast === 0) return null
  const pct = ((event.actual - event.forecast) / Math.abs(event.forecast)) * 100
  if (pct >= 10) return 'large_beat'
  if (pct >= 3)  return 'beat'
  if (pct <= -10) return 'large_miss'
  if (pct <= -3)  return 'miss'
  return 'in_line'
}

const _COL_DAYS = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb']

// Colombia time = UTC-5, no DST — always explicit regardless of browser timezone
function fmtCOL(isoStr) {
  const COL_OFFSET_MS = 5 * 3600000
  const colMs  = new Date(isoStr).getTime() - COL_OFFSET_MS
  const d      = new Date(colMs)
  const nowCol = new Date(Date.now() - COL_OFFSET_MS)

  const hh = String(d.getUTCHours()).padStart(2, '0')
  const mm = String(d.getUTCMinutes()).padStart(2, '0')

  const sameDay = (a, b) =>
    a.getUTCFullYear() === b.getUTCFullYear() &&
    a.getUTCMonth()    === b.getUTCMonth()    &&
    a.getUTCDate()     === b.getUTCDate()

  const tmrCol = new Date(nowCol.getTime() + 86400000)

  const dayLabel = sameDay(d, nowCol) ? 'Hoy'
                 : sameDay(d, tmrCol) ? 'Mañ'
                 : `${_COL_DAYS[d.getUTCDay()]} ${d.getUTCDate()}/${d.getUTCMonth() + 1}`

  return { time: `${hh}:${mm}`, day: dayLabel }
}

function EventRow({ event, selected, onClick }) {
  const isReleased = event.status === 'released'
  const isPast = new Date(event.event_at) < new Date()
  const surpriseLabel = event.surprise_label || inferSurpriseLabel(event)
  const { time: colTime, day: colDay } = fmtCOL(event.event_at)

  return (
    <div
      onClick={() => onClick(event)}
      style={{
        display: 'grid',
        gridTemplateColumns: '60px 16px 1fr auto',
        gap: 8,
        alignItems: 'center',
        padding: '6px 8px',
        borderRadius: 3,
        cursor: 'pointer',
        borderLeft: selected ? '2px solid var(--green)' : '2px solid transparent',
        background: selected ? 'var(--bg-hover)' : 'transparent',
        opacity: isPast && !isReleased ? 0.5 : 1,
        borderBottom: '1px solid var(--border)',
        transition: 'background 0.1s',
      }}
    >
      <div>
        <div style={{ color: 'var(--text-dim)', fontSize: 11 }}>{colTime}</div>
        <div style={{ color: 'var(--text-muted)', fontSize: 9, letterSpacing: 0.3 }}>{colDay} COL</div>
      </div>
      <ImportanceBadge level={event.importance} />
      <div>
        <div style={{ color: isReleased ? 'var(--text-primary)' : 'var(--text-dim)', fontSize: 12 }}>
          {event.event_name}
        </div>
        {isReleased && (
          <div style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 8, marginTop: 2 }}>
            <span>A: <span style={{ color: 'var(--text-primary)' }}>{event.actual ?? '–'}{event.unit || ''}</span></span>
            <span>F: {event.forecast ?? '–'}{event.unit || ''}</span>
            <span>P: {event.previous ?? '–'}{event.unit || ''}</span>
          </div>
        )}
      </div>
      <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', gap: 2, alignItems: 'flex-end' }}>
        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{event.currency}</span>
        {isReleased && <SurpriseBadge label={surpriseLabel} />}
        {!isReleased && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>PENDING</span>}
      </div>
    </div>
  )
}

export default function CalendarPanel({ onEventSelect, selectedEvent }) {
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState({ importance: null, tab: 'upcoming' })
  const [refreshing, setRefreshing] = useState(false)
  const [autoSelected, setAutoSelected] = useState(null)  // key of last auto-selected event

  // Track which "just released" events we've already auto-selected
  const seenReleasedRef = useRef(new Set())

  const CURRENCIES = 'EUR,USD,GBP,CAD'

  async function loadEvents() {
    try {
      let data
      if (filter.tab === 'upcoming') {
        data = await api.getUpcoming({ hours: 120, importance: filter.importance, currencies: CURRENCIES })
      } else {
        data = await api.getRecent({ hours: 72, currencies: CURRENCIES })
      }
      setEvents(data.events || [])
    } catch (e) {
      console.error('Calendar load error:', e)
    } finally {
      setLoading(false)
    }
  }

  // Poll for high-impact events released in the last 15 min — auto-trigger analysis
  async function checkJustReleased() {
    try {
      const data = await api.getJustReleased({ minutes: 45 })
      const events = data.events || []
      if (events.length === 0) return

      // Most recent first — pick the first one we haven't seen yet
      for (const ev of events) {
        const key = ev.event_name + ev.event_at + String(ev.actual ?? '')
        if (!seenReleasedRef.current.has(key)) {
          seenReleasedRef.current.add(key)
          // Auto-select: switch to RELEASED tab and trigger analysis
          setFilter(f => ({ ...f, tab: 'recent' }))
          onEventSelect(ev)
          setAutoSelected(key)
          break  // One auto-selection per poll cycle
        }
      }
    } catch {
      // Silent fail
    }
  }

  useEffect(() => { loadEvents() }, [filter.tab, filter.importance])
  useInterval(loadEvents, 60_000)
  useInterval(checkJustReleased, 30_000)  // Hot-detect new releases every 30s

  async function handleRefresh() {
    setRefreshing(true)
    try { await api.refreshCalendar() } catch (e) {}
    await loadEvents()
    setRefreshing(false)
  }

  const tabStyle = (active) => ({
    padding: '2px 10px',
    borderRadius: 3,
    border: '1px solid',
    borderColor: active ? 'var(--green-dim)' : 'var(--border)',
    color: active ? 'var(--green)' : 'var(--text-muted)',
    background: active ? 'rgba(0,212,170,0.08)' : 'transparent',
    cursor: 'pointer',
    fontSize: 10,
    fontFamily: 'var(--font-mono)',
    letterSpacing: 0.5,
  })

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-header">
        <span className="panel-title">📅 ECONOMIC CALENDAR</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {autoSelected && (
            <span style={{
              fontSize: 9, color: 'var(--green)', letterSpacing: 0.5,
              animation: 'pulse 2s infinite',
            }}>
              ⚡ AUTO
            </span>
          )}
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{events.length} events</span>
          <button
            className="btn"
            onClick={handleRefresh}
            disabled={refreshing}
            style={{ fontSize: 10 }}
          >
            {refreshing ? '⟳ ...' : '⟳ REFRESH'}
          </button>
        </div>
      </div>

      {/* Tabs + Filters */}
      <div style={{
        display: 'flex', gap: 6, padding: '6px 8px',
        borderBottom: '1px solid var(--border)', flexShrink: 0,
        flexWrap: 'wrap',
      }}>
        <button style={tabStyle(filter.tab === 'upcoming')} onClick={() => setFilter(f => ({ ...f, tab: 'upcoming' }))}>UPCOMING</button>
        <button style={tabStyle(filter.tab === 'recent')} onClick={() => setFilter(f => ({ ...f, tab: 'recent' }))}>RELEASED</button>
        <div style={{ width: 1, background: 'var(--border)', margin: '0 2px' }} />
        {['high', 'medium', null].map(imp => (
          <button
            key={String(imp)}
            style={tabStyle(filter.importance === imp)}
            onClick={() => setFilter(f => ({ ...f, importance: imp }))}
          >
            {imp ? imp.toUpperCase() : 'ALL'}
          </button>
        ))}
      </div>

      <div className="panel-body" style={{ padding: 0 }}>
        {loading ? (
          <div style={{ padding: 16, color: 'var(--text-muted)', textAlign: 'center' }}>Loading...</div>
        ) : events.length === 0 ? (
          <div style={{ padding: 16, color: 'var(--text-muted)', textAlign: 'center' }}>
            No events found. Click REFRESH to load from FRED.
          </div>
        ) : (
          events.map(ev => (
            <EventRow
              key={ev.id || ev.event_name + ev.event_at}
              event={ev}
              selected={selectedEvent?.event_name === ev.event_name && selectedEvent?.event_at === ev.event_at}
              onClick={onEventSelect}
            />
          ))
        )}
      </div>
    </div>
  )
}
