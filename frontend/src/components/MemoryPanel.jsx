import { useState, useEffect, useCallback } from 'react'
import { api } from '../api/index.js'

function MoveCell({ value }) {
  if (value == null) return <span style={{ color: 'var(--text-muted)' }}>–</span>
  const pos = value >= 0
  return (
    <span style={{ color: pos ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
      {pos ? '+' : ''}{value.toFixed(2)}%
    </span>
  )
}

function HistConfidenceBar({ data }) {
  if (!data || data.based_on === 0) return (
    <div style={{ padding: '6px 0', color: 'var(--text-muted)', fontSize: 10, textAlign: 'center' }}>
      Sin historial aún — analiza eventos para construir memoria
    </div>
  )

  const score = data.score
  const color = score >= 70 ? 'var(--green)' : score >= 45 ? 'var(--blue)' : 'var(--red)'

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '4px 0' }}>
      {/* Score circle */}
      <div style={{
        width: 44, height: 44, borderRadius: '50%', flexShrink: 0,
        background: `conic-gradient(${color} ${score * 3.6}deg, var(--bg-primary) 0deg)`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{
          width: 34, height: 34, borderRadius: '50%', background: 'var(--bg-secondary)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 13, fontWeight: 900, color,
        }}>
          {score}
        </div>
      </div>
      {/* Stats */}
      <div style={{ flex: 1, fontSize: 10, lineHeight: 1.7 }}>
        <div style={{ color: 'var(--text-muted)', letterSpacing: 1, fontSize: 9 }}>HIST. CONFIDENCE</div>
        <div style={{ display: 'flex', gap: 10 }}>
          <span style={{ color: 'var(--green)' }}>▲ {data.gold_up_pct ?? '–'}%</span>
          <span style={{ color: 'var(--red)' }}>▼ {data.gold_down_pct ?? '–'}%</span>
          {data.avg_gold_1h != null && (
            <span style={{ color: 'var(--text-dim)' }}>
              avg {data.avg_gold_1h > 0 ? '+' : ''}{data.avg_gold_1h}%
            </span>
          )}
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>{data.message}</div>
      </div>
    </div>
  )
}

function PatternCard({ patterns }) {
  if (!patterns || patterns.total_events === 0) return null
  return (
    <div style={{
      background: 'var(--bg-card)', border: '1px solid var(--border)',
      borderRadius: 3, padding: '6px 8px', marginBottom: 6,
    }}>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 4 }}>
        PATRONES HISTÓRICOS — {patterns.total_events} EVENTOS
      </div>
      <div style={{ display: 'flex', gap: 8, fontSize: 10 }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>GOLD UP 1H</div>
          <div style={{ color: 'var(--green)', fontWeight: 700 }}>{patterns.gold_up_1h_pct}%</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>AVG GOLD 1H</div>
          <div style={{ color: patterns.avg_gold_move_1h >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
            {patterns.avg_gold_move_1h > 0 ? '+' : ''}{patterns.avg_gold_move_1h}%
          </div>
        </div>
        {patterns.high_nss_accuracy != null && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>NSS{'>'}70 ACC</div>
            <div style={{ color: 'var(--blue)', fontWeight: 700 }}>{patterns.high_nss_accuracy}%</div>
          </div>
        )}
        {patterns.high_iss_accuracy != null && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>ISS{'>'}70 ACC</div>
            <div style={{ color: 'var(--amber)', fontWeight: 700 }}>{patterns.high_iss_accuracy}%</div>
          </div>
        )}
      </div>
    </div>
  )
}

function MemoryRow({ m }) {
  const sentColor = m.sentiment === 'bullish_gold' ? 'var(--green)'
    : m.sentiment === 'bearish_gold' ? 'var(--red)' : 'var(--text-muted)'

  const statusDot = m.status === 'complete' ? '●' : m.status === 'partial' ? '◐' : '○'
  const statusColor = m.status === 'complete' ? 'var(--green)' : m.status === 'partial' ? 'var(--amber)' : 'var(--text-muted)'

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: '1fr 36px 36px 36px 36px 36px 36px 10px',
      gap: 4,
      padding: '3px 0',
      borderBottom: '1px solid var(--border)',
      fontSize: 9,
      alignItems: 'center',
    }}>
      <div style={{ overflow: 'hidden' }}>
        <div style={{ color: 'var(--text-dim)', fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {m.event_name}
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 8 }}>
          {m.event_at ? new Date(m.event_at).toLocaleDateString('es', { month: 'short', day: 'numeric' }) : '–'}
          {m.iss != null && <span style={{ color: sentColor, marginLeft: 4 }}>ISS {m.iss}</span>}
        </div>
      </div>
      <MoveCell value={m.gold_move_5m} />
      <MoveCell value={m.gold_move_15m} />
      <MoveCell value={m.gold_move_1h} />
      <MoveCell value={m.gold_move_4h} />
      <MoveCell value={m.dxy_move_1h} />
      <MoveCell value={m.us10y_move_1h} />
      <span style={{ color: statusColor, fontSize: 8 }}>{statusDot}</span>
    </div>
  )
}

export default function MemoryPanel({ event }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async (filterEvent = null) => {
    setLoading(true)
    try {
      const params = filterEvent ? { event_name: filterEvent.event_name, limit: 20 } : { limit: 20 }
      const res = await api.getEventMemory(params)
      setData(res)
    } catch { /* silent */ } finally {
      setLoading(false)
    }
  }, [])

  // Initial load + refresh every 2 minutes
  useEffect(() => {
    load(event)
    const id = setInterval(() => load(event), 120_000)
    return () => clearInterval(id)
  }, [event, load])

  const memories = data?.memories || []
  const patterns = data?.patterns
  const conf     = data?.historical_confidence

  return (
    <div className="panel" style={{ flex: 1, overflow: 'hidden', minWidth: 0 }}>
      <div className="panel-header" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span className="panel-title">📚 EVENT MEMORY</span>
        {data && (
          <span className="badge" style={{ fontSize: 8 }}>
            {data.total} registros
          </span>
        )}
        <button
          onClick={() => load(event)}
          disabled={loading}
          style={{
            marginLeft: 'auto', background: 'none', border: '1px solid var(--border)',
            color: 'var(--text-muted)', borderRadius: 2, padding: '1px 6px',
            cursor: 'pointer', fontSize: 9,
          }}
        >
          {loading ? '...' : '↻'}
        </button>
      </div>

      <div className="panel-body" style={{ overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {/* Historical Confidence */}
        <HistConfidenceBar data={conf} />

        {/* Pattern stats */}
        <PatternCard patterns={patterns} />

        {/* Table header */}
        {memories.length > 0 && (
          <>
            <div style={{
              display: 'grid',
              gridTemplateColumns: '1fr 36px 36px 36px 36px 36px 36px 10px',
              gap: 4,
              fontSize: 8,
              color: 'var(--text-muted)',
              letterSpacing: 0.5,
              padding: '2px 0',
              borderBottom: '1px solid var(--border)',
            }}>
              <span>EVENTO</span>
              <span>5m</span>
              <span>15m</span>
              <span>1h</span>
              <span>4h</span>
              <span>DXY</span>
              <span>10Y</span>
              <span />
            </div>
            {memories.map(m => <MemoryRow key={m.id} m={m} />)}
          </>
        )}

        {!loading && memories.length === 0 && (
          <div style={{ padding: 12, textAlign: 'center', color: 'var(--text-muted)', fontSize: 10 }}>
            Sin registros aún. Analiza un evento con actual + forecast para iniciar la memoria.
          </div>
        )}
      </div>
    </div>
  )
}
