import { useState, useEffect, useRef } from 'react'
import { api } from '../api/index.js'
import { useSound } from '../hooks/useSound.js'

// ── Label config ─────────────────────────────────────────────────────────────
const LABEL_CONFIG = {
  large_beat: { color: 'var(--green)',   label: 'LARGE BEAT',  bg: 'rgba(0,212,170,0.1)' },
  beat:       { color: 'var(--green)',   label: 'BEAT',        bg: 'rgba(0,212,170,0.08)' },
  in_line:    { color: 'var(--blue)',    label: 'IN LINE',     bg: 'rgba(64,144,255,0.08)' },
  miss:       { color: 'var(--red)',     label: 'MISS',        bg: 'rgba(255,68,85,0.08)' },
  large_miss: { color: 'var(--red)',     label: 'LARGE MISS',  bg: 'rgba(255,68,85,0.1)' },
}

// ── Section header colours (covers both 4-line tactical + 8-line briefing) ───
const SECTION_COLORS = {
  // Tactical 4-line format
  'SEÑAL:':   'var(--green)',
  'SCORES:':  '#ffaa00',
  'PRECIO:':  'var(--blue)',
  'ACCIÓN:':  '#cc88ff',
  // Briefing 8-line format
  'CONTEXTO:':  'var(--blue)',
  'NARRATIVA:': '#ffaa00',
  'CLAVE:':     'var(--green)',
  'HORARIO:':   'var(--text-primary)',
  'CADENA:':    '#cc88ff',
  'TRADING:':   'var(--red)',
  'SESGO:':     '#00ffcc',
  // Legacy labels (from older format variants)
  'RESUMEN:':                'var(--blue)',
  'IMPACTO:':                '#ffaa00',
  'LECTURA INSTITUCIONAL:':  'var(--text-primary)',
  'VISION SMART MONEY:':     '#cc88ff',
  'VISIÓN SMART MONEY:':     '#cc88ff',
}

// ── Shared sub-components ─────────────────────────────────────────────────────
function ImpactBar({ label, value }) {
  const absVal    = Math.abs(value)
  const isPositive = value >= 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
      <span style={{ width: 52, color: 'var(--text-dim)', fontSize: 11 }}>{label}</span>
      <div style={{ flex: 1, height: 6, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: `${absVal}%`,
          background: isPositive ? 'var(--green)' : 'var(--red)',
          borderRadius: 3,
          transition: 'width 0.5s ease',
          marginLeft: isPositive ? 0 : `${100 - absVal}%`,
        }} />
      </div>
      <span style={{ width: 40, textAlign: 'right', color: isPositive ? 'var(--green)' : 'var(--red)', fontSize: 11 }}>
        {value > 0 ? '+' : ''}{value}
      </span>
    </div>
  )
}

function AnalysisText({ text }) {
  const lines = text.split('\n')
  return (
    <div style={{ fontSize: 12, lineHeight: 1.7, color: 'var(--text-dim)' }}>
      {lines.map((line, i) => {
        const trimmed = line.trim()
        const sectionColor = Object.entries(SECTION_COLORS).find(([k]) =>
          trimmed.toUpperCase().startsWith(k.toUpperCase())
        )?.[1]

        // ACCIÓN: can be green (LONG/LONG) or red (SHORT/ESPERAR) depending on content
        let color = sectionColor
        if (trimmed.toUpperCase().startsWith('ACCIÓN:') || trimmed.toUpperCase().startsWith('ACCION:')) {
          const upper = trimmed.toUpperCase()
          if (upper.includes('PREPARAR_LONG') || upper.includes('LONG ')) color = 'var(--green)'
          else if (upper.includes('PREPARAR_SHORT') || upper.includes('SHORT ')) color = 'var(--red)'
          else color = '#cc88ff'
        }
        // SESGO: green if ALCISTA, red if BAJISTA
        if (trimmed.toUpperCase().startsWith('SESGO:')) {
          const upper = trimmed.toUpperCase()
          if (upper.includes('ALCISTA')) color = 'var(--green)'
          else if (upper.includes('BAJISTA')) color = 'var(--red)'
          else color = '#ffaa00'
        }
        // SEÑAL: green if ALCISTA, red if BAJISTA
        if (trimmed.toUpperCase().startsWith('SEÑAL:') || trimmed.toUpperCase().startsWith('SENAL:')) {
          const upper = trimmed.toUpperCase()
          if (upper.includes('ALCISTA')) color = 'var(--green)'
          else if (upper.includes('BAJISTA')) color = 'var(--red)'
          else color = '#4090ff'
        }

        const isHeader = Boolean(color) || /^[^\w]*[A-ZÁÉÍÓÚ]{3,}.*:/.test(trimmed)

        return (
          <div key={i} style={{
            color:      isHeader ? (color || 'var(--text-primary)') : 'var(--text-dim)',
            fontWeight: isHeader ? 700 : 400,
            marginTop:  isHeader ? 8 : 0,
            lineHeight: isHeader ? 2 : 1.6,
          }}>
            {line || ' '}
          </div>
        )
      })}
    </div>
  )
}

// ── Tab button ────────────────────────────────────────────────────────────────
function TabBtn({ active, color = 'var(--green)', onClick, children }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: '3px 12px',
        fontSize: 10,
        letterSpacing: 1,
        fontFamily: 'var(--font-mono)',
        background: active ? `${color}22` : 'transparent',
        color:  active ? color : 'var(--text-muted)',
        border: `1px solid ${active ? color : 'var(--border)'}`,
        borderRadius: 2,
        cursor: 'pointer',
        transition: 'all 0.15s',
      }}
    >
      {children}
    </button>
  )
}

// ── Main component ────────────────────────────────────────────────────────────
export default function AnalysisPanel({ event, onSurpriseComputed }) {
  const [tab, setTab] = useState('briefing')   // 'briefing' | 'analysis'
  const [analysis, setAnalysis] = useState({ loading: false, data: null, surprise: null, error: null })
  const [briefing, setBriefing] = useState({ loading: false, data: null, error: null })
  const { playDataRelease } = useSound()
  const prevEventKey = useRef(null)

  // Auto-load briefing on mount
  useEffect(() => {
    loadBriefing(false)
  }, [])

  // When a released event is selected → auto-switch to analysis tab
  useEffect(() => {
    if (!event) return
    const key = event.event_name + event.event_at + String(event.actual ?? '')
    if (prevEventKey.current === key) return
    prevEventKey.current = key

    if (event.actual == null || event.forecast == null) {
      setAnalysis({ loading: false, data: null, surprise: null, error: null })
      return
    }

    setTab('analysis')
    runAnalysis(event)
  }, [event])

  // ── Data loaders ──────────────────────────────────────────────────────────

  async function loadBriefing(force) {
    setBriefing(s => ({ ...s, loading: true, error: null }))
    try {
      const data = await api.getDailyBriefing(force)
      setBriefing({ loading: false, data, error: null })
    } catch (e) {
      setBriefing({ loading: false, data: null, error: String(e) })
    }
  }

  async function runAnalysis(ev) {
    setAnalysis(s => ({ ...s, loading: true, error: null }))
    try {
      const surprise = await api.computeSurprise({
        event_name: ev.event_name,
        actual:     ev.actual,
        forecast:   ev.forecast,
        previous:   ev.previous,
        currency:   ev.currency,
        unit:       ev.unit,
      })

      playDataRelease(surprise.surprise_pct > 0)

      const result = await api.analyzeEvent({
        event_name:    ev.event_name,
        actual:        ev.actual,
        forecast:      ev.forecast,
        previous:      ev.previous,
        surprise_pct:  surprise.surprise_pct,
        surprise_label: surprise.surprise_label,
        currency:      ev.currency,
        importance:    ev.importance,
        unit:          ev.unit,
      })

      setAnalysis({ loading: false, data: result, surprise, error: null })
      if (onSurpriseComputed) onSurpriseComputed(surprise)
    } catch (e) {
      setAnalysis({ loading: false, data: null, surprise: null, error: String(e) })
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  const cfg = LABEL_CONFIG[analysis.surprise?.surprise_label] || {}

  return (
    <div className="panel" style={{ flex: 1 }}>

      {/* ── Header + tab bar ─────────────────────────────────────────────── */}
      <div className="panel-header" style={{ flexDirection: 'column', gap: 0, paddingBottom: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
          <span className="panel-title">AI ANALYSIS — SMART MONEY</span>
          {tab === 'analysis' && analysis.surprise && (
            <span className="badge" style={{ background: cfg.bg, color: cfg.color, borderColor: `${cfg.color}44` }}>
              {cfg.label} · {analysis.surprise.surprise_pct > 0 ? '+' : ''}{analysis.surprise.surprise_pct?.toFixed(2)}%
            </span>
          )}
          {tab === 'briefing' && briefing.data && (
            <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
              {new Date(briefing.data.generated_at).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })} · {briefing.data.tokens_used}t
            </span>
          )}
        </div>

        {/* Tab row */}
        <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
          <TabBtn active={tab === 'briefing'} color="var(--green)" onClick={() => setTab('briefing')}>
            BRIEFING MACRO
          </TabBtn>
          <TabBtn active={tab === 'analysis'} color="var(--blue)" onClick={() => setTab('analysis')}>
            ANÁLISIS EVENTO
          </TabBtn>
          {tab === 'briefing' && (
            <button
              onClick={() => loadBriefing(true)}
              disabled={briefing.loading}
              title="Regenerar briefing"
              style={{
                marginLeft: 'auto',
                padding: '3px 8px',
                fontSize: 10,
                fontFamily: 'var(--font-mono)',
                background: 'transparent',
                color: briefing.loading ? 'var(--text-muted)' : 'var(--text-dim)',
                border: '1px solid var(--border)',
                borderRadius: 2,
                cursor: briefing.loading ? 'default' : 'pointer',
              }}
            >
              {briefing.loading ? '...' : '↻ ACTUALIZAR'}
            </button>
          )}
        </div>
      </div>

      {/* ── Panel body ───────────────────────────────────────────────────── */}
      <div className="panel-body">

        {/* ═══════════════════ BRIEFING TAB ═══════════════════════════════ */}
        {tab === 'briefing' && (
          <>
            {briefing.loading && (
              <div style={{ padding: 20, textAlign: 'center' }}>
                <div style={{ color: 'var(--green)', marginBottom: 8, fontSize: 12 }}>
                  <span className="pulse">◉</span> Generando briefing macro del día...
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                  Claude Opus · Por qué · Cuándo · Cómo
                </div>
              </div>
            )}

            {briefing.error && !briefing.loading && (
              <div style={{ padding: 12, color: 'var(--red)', fontSize: 12, background: 'rgba(255,68,85,0.08)', borderRadius: 4 }}>
                {briefing.error}
              </div>
            )}

            {briefing.data && !briefing.loading && (
              <div style={{
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                borderRadius: 4,
                padding: '14px',
              }}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  marginBottom: 10,
                }}>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1 }}>
                    CONTEXTO MACRO DEL DÍA · {briefing.data.model?.split('-').slice(0,2).join(' ').toUpperCase()}
                  </div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>
                    {briefing.data.upcoming_count} próximos · {briefing.data.released_count} publicados
                  </div>
                </div>
                <AnalysisText text={briefing.data.briefing || ''} />
              </div>
            )}

            {!briefing.data && !briefing.loading && !briefing.error && (
              <div style={{ padding: 20, textAlign: 'center' }}>
                <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                  Cargando contexto macro...
                </div>
              </div>
            )}
          </>
        )}

        {/* ═══════════════════ ANALYSIS TAB ═══════════════════════════════ */}
        {tab === 'analysis' && (
          <>
            {/* No event selected */}
            {!event && (
              <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 }}>
                <span style={{ fontSize: 28 }}>&#x1F3E6;</span>
                <span style={{ color: 'var(--text-muted)', textAlign: 'center', fontSize: 12 }}>
                  Selecciona un evento del calendario<br />para generar análisis institucional
                </span>
                <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                  Solo eventos con Actual + Forecast disponibles
                </span>
              </div>
            )}

            {/* Event selected */}
            {event && (
              <>
                {/* Event header */}
                <div style={{
                  background: 'var(--bg-card)', border: '1px solid var(--border)',
                  borderRadius: 4, padding: '10px 12px', marginBottom: 10,
                }}>
                  <div style={{ fontWeight: 700, fontSize: 13, marginBottom: 6 }}>{event.event_name}</div>
                  <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
                    <span>Actual: <strong style={{ color: 'var(--text-primary)' }}>{event.actual ?? '–'}{event.unit || ''}</strong></span>
                    <span>Forecast: <span style={{ color: 'var(--text-dim)' }}>{event.forecast ?? '–'}{event.unit || ''}</span></span>
                    <span>Prev: <span style={{ color: 'var(--text-muted)' }}>{event.previous ?? '–'}{event.unit || ''}</span></span>
                  </div>
                </div>

                {/* Surprise metrics */}
                {analysis.surprise && (
                  <div style={{
                    background: cfg.bg || 'var(--bg-card)',
                    border: `1px solid ${cfg.color || 'var(--border)'}44`,
                    borderRadius: 4, padding: '10px 12px', marginBottom: 10,
                  }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                      <span style={{ color: 'var(--text-dim)', fontSize: 11, letterSpacing: 1 }}>SURPRISE SCORE</span>
                      <span style={{ color: cfg.color, fontWeight: 700 }}>
                        {analysis.surprise.surprise_pct > 0 ? '+' : ''}{analysis.surprise.surprise_pct?.toFixed(2)}%
                      </span>
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>ASSET IMPACT SCORES</div>
                    {analysis.surprise.asset_impacts && Object.entries(analysis.surprise.asset_impacts).map(([asset, val]) => (
                      <ImpactBar key={asset} label={asset} value={val} />
                    ))}
                  </div>
                )}

                {/* Loading */}
                {analysis.loading && (
                  <div style={{ padding: 16, textAlign: 'center' }}>
                    <div style={{ color: 'var(--green)', marginBottom: 8, fontSize: 12 }}>
                      <span className="pulse">◉</span> Generando análisis institucional...
                    </div>
                    <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                      Claude Opus · Smart Money methodology
                    </div>
                  </div>
                )}

                {/* Error */}
                {analysis.error && (
                  <div style={{ padding: 12, color: 'var(--red)', fontSize: 12, background: 'rgba(255,68,85,0.1)', borderRadius: 4 }}>
                    Error: {analysis.error}
                  </div>
                )}

                {/* AI analysis result */}
                {analysis.data && !analysis.loading && (
                  <div style={{
                    background: 'var(--bg-card)', border: '1px solid var(--border)',
                    borderRadius: 4, padding: '12px',
                  }}>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8, letterSpacing: 1 }}>
                      ANÁLISIS INSTITUCIONAL · {analysis.data.model?.split('-').slice(0,2).join(' ').toUpperCase()} · {analysis.data.tokens_used} TOKENS
                    </div>
                    <AnalysisText text={analysis.data.analysis || ''} />
                  </div>
                )}

                {/* No data yet */}
                {!analysis.loading && !analysis.data && !analysis.error && event.actual == null && (
                  <div style={{ padding: 16, color: 'var(--text-muted)', textAlign: 'center', fontSize: 12 }}>
                    Este evento aún no tiene datos publicados (Actual = null)
                  </div>
                )}
              </>
            )}
          </>
        )}

      </div>
    </div>
  )
}
