import { useState, useEffect } from 'react'
import { api } from '../api/index.js'

// ISS classification colours
const CLASS_COLORS = {
  'EXTREME BULLISH':    '#00ff88',
  'BULLISH':            '#00d4aa',
  'MODERATELY BULLISH': '#66ffaa',
  'NEUTRAL':            '#4090ff',
  'BEARISH':            '#ff4455',
  'EXTREME BEARISH':    '#cc0011',
}

function IssGauge({ score, classification }) {
  const color = CLASS_COLORS[classification?.label] || '#4090ff'
  const pct   = score || 0

  return (
    <div style={{ textAlign: 'center', padding: '8px 0' }}>
      {/* Arc label */}
      <div style={{ fontSize: 11, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 4 }}>
        INSTITUTIONAL SENTIMENT SCORE
      </div>

      {/* Score circle */}
      <div style={{
        width: 80, height: 80, borderRadius: '50%', margin: '0 auto 8px',
        background: `conic-gradient(${color} ${pct * 3.6}deg, var(--bg-card) 0deg)`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        position: 'relative',
      }}>
        <div style={{
          width: 64, height: 64, borderRadius: '50%',
          background: 'var(--bg-secondary)',
          display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{ fontSize: 20, fontWeight: 900, color, lineHeight: 1 }}>{pct}</span>
          <span style={{ fontSize: 8, color: 'var(--text-muted)' }}>/ 100</span>
        </div>
      </div>

      {/* Classification badge */}
      <div style={{
        display: 'inline-block', padding: '3px 10px', borderRadius: 3,
        background: `${color}22`, border: `1px solid ${color}66`,
        fontSize: 10, fontWeight: 700, color, letterSpacing: 1,
      }}>
        {classification?.label || 'NEUTRAL'}
      </div>
    </div>
  )
}

function ScoreBar({ label, score, color }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
      <span style={{ width: 36, fontSize: 10, color: 'var(--text-muted)' }}>{label}</span>
      <div style={{ flex: 1, height: 5, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${score || 0}%`, background: color, borderRadius: 3, transition: 'width 0.6s ease' }} />
      </div>
      <span style={{ width: 28, textAlign: 'right', fontSize: 10, color }}>{score || 0}</span>
    </div>
  )
}

function WindowRow({ label, assets }) {
  if (!assets) return null
  const confirms = Object.values(assets).filter(a => a?.confirms === true).length
  const total    = Object.values(assets).filter(a => a?.confirms !== null).length
  const allNull  = total === 0
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 6,
      padding: '2px 0', borderBottom: '1px solid var(--border)',
      fontSize: 10,
    }}>
      <span style={{ width: 24, color: 'var(--text-muted)', fontWeight: 700 }}>{label}</span>
      {allNull ? (
        <span style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>sin datos</span>
      ) : (
        Object.entries(assets).map(([sym, info]) => {
          if (!info || info.change_pct === null) return null
          const col = info.confirms ? 'var(--green)' : 'var(--red)'
          const arrow = info.actual === 'up' ? '▲' : info.actual === 'down' ? '▼' : '→'
          return (
            <span key={sym} title={`${sym}: ${info.change_pct > 0 ? '+' : ''}${info.change_pct?.toFixed(2)}%`}
              style={{ color: col, fontSize: 9 }}>
              {sym.slice(0, 3)}{arrow}
            </span>
          )
        })
      )}
      {!allNull && (
        <span style={{ marginLeft: 'auto', color: confirms === total ? 'var(--green)' : confirms > 0 ? 'var(--amber)' : 'var(--red)', fontSize: 9 }}>
          {confirms}/{total}✓
        </span>
      )}
    </div>
  )
}

export default function SentimentPanel({ event }) {
  const [iss, setIss]         = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [lastEvent, setLastEvent] = useState(null)

  // When a new event is selected and analyzed, trigger ISS
  useEffect(() => {
    if (!event) return
    const key = `${event.event_name}:${event.actual}:${event.forecast}`
    if (key === lastEvent) return
    if (event.actual == null || event.forecast == null) return
    setLastEvent(key)
    fetchIss(event)
  }, [event])

  async function fetchIss(ev) {
    setLoading(true)
    setError(null)
    try {
      const surprise_pct = (ev.actual != null && ev.forecast != null && ev.forecast !== 0)
        ? ((ev.actual - ev.forecast) / Math.abs(ev.forecast)) * 100
        : (ev.surprise_pct ?? 0)

      const result = await api.analyzeSentiment({
        event_name:   ev.event_name,
        actual:       ev.actual,
        forecast:     ev.forecast,
        previous:     ev.previous,
        surprise_pct: surprise_pct,
        currency:     ev.currency || 'USD',
      })
      setIss(result)
    } catch (e) {
      setError(String(e))
    } finally {
      setLoading(false)
    }
  }

  // Empty state
  if (!event || (event.actual == null || event.forecast == null)) {
    return (
      <div className="panel" style={{ flex: 1 }}>
        <div className="panel-header">
          <span className="panel-title">📡 INSTITUTIONAL SENTIMENT ENGINE</span>
        </div>
        <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
          <span style={{ fontSize: 28 }}>📡</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 11, textAlign: 'center' }}>
            ISS activo tras analizar un evento<br />NSS · MCS · ISS = 60%+40%
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="panel" style={{ flex: 1, overflow: 'hidden' }}>
      <div className="panel-header">
        <span className="panel-title">📡 INSTITUTIONAL SENTIMENT ENGINE</span>
        {iss && (
          <span className="badge" style={{ fontSize: 9 }}>
            ISS {iss.iss} · {iss.classification?.label}
          </span>
        )}
      </div>

      <div className="panel-body" style={{ overflowY: 'auto' }}>
        {loading && (
          <div style={{ padding: 12, textAlign: 'center', color: 'var(--green)', fontSize: 11 }}>
            <span className="pulse">●</span> Calculando NSS + MCS → ISS...
          </div>
        )}

        {error && (
          <div style={{ padding: 8, color: 'var(--red)', fontSize: 11, background: 'rgba(255,68,85,0.1)', borderRadius: 4 }}>
            ❌ {error}
          </div>
        )}

        {iss && !loading && (
          <>
            {/* ISS Gauge */}
            <IssGauge score={iss.iss} classification={iss.classification} />

            {/* Sesgo + Intensidad */}
            <div style={{ display: 'flex', gap: 6, margin: '8px 0', fontSize: 10 }}>
              <div style={{ flex: 1, background: 'var(--bg-card)', borderRadius: 3, padding: '5px 8px', textAlign: 'center' }}>
                <div style={{ color: 'var(--text-muted)', marginBottom: 2 }}>SESGO</div>
                <div style={{ fontWeight: 700, color: CLASS_COLORS[iss.classification?.label] || 'var(--text-primary)' }}>
                  {iss.sesgo}
                </div>
              </div>
              <div style={{ flex: 1, background: 'var(--bg-card)', borderRadius: 3, padding: '5px 8px', textAlign: 'center' }}>
                <div style={{ color: 'var(--text-muted)', marginBottom: 2 }}>INTENSIDAD</div>
                <div style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{iss.intensidad}</div>
              </div>
            </div>

            {/* NSS / MCS score bars */}
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 4 }}>COMPONENTES ISS</div>
              <ScoreBar label="NSS"  score={iss.nss?.score}  color="var(--green)" />
              <ScoreBar label="MCS"  score={iss.mcs?.score}  color="var(--blue)" />
              <ScoreBar label="ISS"  score={iss.iss}         color={CLASS_COLORS[iss.classification?.label] || '#4090ff'} />
              <div style={{ fontSize: 8, color: 'var(--text-muted)', marginTop: 2 }}>{iss.formula}</div>
            </div>

            {/* Probabilidades */}
            <div style={{ display: 'flex', gap: 6, marginBottom: 8, fontSize: 10 }}>
              <div style={{ flex: 1, textAlign: 'center', background: 'rgba(0,212,170,0.08)', borderRadius: 3, padding: '4px' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>PROB ALCISTA</div>
                <div style={{ color: 'var(--green)', fontWeight: 700, fontSize: 13 }}>
                  {iss.nss?.bull_probability ?? 50}%
                </div>
              </div>
              <div style={{ flex: 1, textAlign: 'center', background: 'rgba(255,68,85,0.08)', borderRadius: 3, padding: '4px' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>PROB BAJISTA</div>
                <div style={{ color: 'var(--red)', fontWeight: 700, fontSize: 13 }}>
                  {iss.nss?.bear_probability ?? 50}%
                </div>
              </div>
              <div style={{ flex: 1, textAlign: 'center', background: 'rgba(64,144,255,0.08)', borderRadius: 3, padding: '4px' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: 9 }}>CONFIANZA</div>
                <div style={{ color: 'var(--blue)', fontWeight: 700, fontSize: 13 }}>
                  {iss.nss?.confidence ?? 0}%
                </div>
              </div>
            </div>

            {/* NSS explanation */}
            {iss.nss?.explanation && (
              <div style={{
                background: 'var(--bg-card)', border: '1px solid var(--border)',
                borderRadius: 3, padding: '6px 8px', marginBottom: 8,
                fontSize: 10, color: 'var(--text-dim)', lineHeight: 1.6,
              }}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', marginBottom: 3, letterSpacing: 1 }}>
                  NSS — LECTURA CLAUDE
                </div>
                {iss.nss.explanation}
              </div>
            )}

            {/* MCS windows */}
            {iss.mcs?.windows && Object.keys(iss.mcs.windows).length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 4 }}>
                  MCS — CONFIRMACIÓN PRECIO ({iss.mcs?.data_available ? `${iss.mcs.total_points}/${iss.mcs.max_points} confirman` : 'acumulando datos...'})
                </div>
                {Object.entries(iss.mcs.windows).map(([win, assets]) => (
                  <WindowRow key={win} label={win} assets={assets} />
                ))}
              </div>
            )}

            {/* Divergence alert */}
            {iss.divergence_alert && (
              <div style={{
                padding: '7px 10px', borderRadius: 4, marginTop: 4,
                background: 'rgba(255,170,0,0.1)', border: '1px solid rgba(255,170,0,0.4)',
                fontSize: 10, color: 'var(--amber)', lineHeight: 1.6, fontWeight: 600,
              }}>
                {iss.divergence_alert.message}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
