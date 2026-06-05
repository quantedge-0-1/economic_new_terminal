import { useState, useEffect, useRef } from 'react'
import { api } from '../api/index.js'
import { useSound } from '../hooks/useSound.js'

const LABEL_CONFIG = {
  large_beat: { color: 'var(--green)',   label: 'LARGE BEAT',  bg: 'rgba(0,212,170,0.1)' },
  beat:       { color: 'var(--green)',   label: 'BEAT',        bg: 'rgba(0,212,170,0.08)' },
  in_line:    { color: 'var(--blue)',    label: 'IN LINE',     bg: 'rgba(64,144,255,0.08)' },
  miss:       { color: 'var(--red)',     label: 'MISS',        bg: 'rgba(255,68,85,0.08)' },
  large_miss: { color: 'var(--red)',     label: 'LARGE MISS',  bg: 'rgba(255,68,85,0.1)' },
}

// Colour map for new-format section headers
const SECTION_COLORS = {
  'RESUMEN:':                'var(--blue)',
  'IMPACTO:':                'var(--amber)',
  'FUERZA DEL EVENTO:':      'var(--green)',
  'LECTURA INSTITUCIONAL:':  'var(--text-primary)',
  'ESCENARIO':               'var(--green)',
  'RIESGOS:':                'var(--red)',
  'VISION SMART MONEY:':     '#cc88ff',
  'VISIÓN SMART MONEY:':     '#cc88ff',
}

function ImpactBar({ label, value }) {
  const absVal = Math.abs(value)
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

        // Detect section headers (new format: KEYWORD: or old emoji format)
        const sectionColor = Object.entries(SECTION_COLORS).find(([k]) =>
          trimmed.toUpperCase().startsWith(k.toUpperCase())
        )?.[1]

        const isHeader = Boolean(sectionColor) ||
          trimmed.startsWith('FUERZA') ||
          /^[^\w]*[A-Z]{3,}.*:/.test(trimmed)   // ALL-CAPS word followed by colon

        return (
          <div key={i} style={{
            color: isHeader ? (sectionColor || 'var(--text-primary)') : 'var(--text-dim)',
            fontWeight: isHeader ? 700 : 400,
            marginTop: isHeader ? 10 : 0,
            lineHeight: isHeader ? 2 : 1.6,
          }}>
            {line || ' '}
          </div>
        )
      })}
    </div>
  )
}

export default function AnalysisPanel({ event, onSurpriseComputed }) {
  const [state, setState] = useState({ loading: false, analysis: null, surprise: null, error: null })
  const { playDataRelease } = useSound()
  const prevEvent = useRef(null)

  useEffect(() => {
    if (!event) return
    const key = event.event_name + event.event_at + String(event.actual ?? '')
    if (prevEvent.current === key) return
    prevEvent.current = key

    if (event.actual == null || event.forecast == null) {
      setState({ loading: false, analysis: null, surprise: null, error: null })
      return
    }

    runAnalysis(event)
  }, [event])

  async function runAnalysis(ev) {
    setState(s => ({ ...s, loading: true, error: null }))
    try {
      const surprise = await api.computeSurprise({
        event_name: ev.event_name,
        actual: ev.actual,
        forecast: ev.forecast,
        previous: ev.previous,
        currency: ev.currency,
        unit: ev.unit,
      })

      playDataRelease(surprise.surprise_pct > 0)

      const analysis = await api.analyzeEvent({
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

      setState({ loading: false, analysis, surprise, error: null })
      if (onSurpriseComputed) onSurpriseComputed(surprise)
    } catch (e) {
      setState({ loading: false, analysis: null, surprise: null, error: String(e) })
    }
  }

  if (!event) {
    return (
      <div className="panel" style={{ flex: 1 }}>
        <div className="panel-header">
          <span className="panel-title">AI ANALYSIS — SMART MONEY</span>
        </div>
        <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12 }}>
          <span style={{ fontSize: 32 }}>&#x1F3E6;</span>
          <span style={{ color: 'var(--text-muted)', textAlign: 'center', fontSize: 12 }}>
            Selecciona un evento del calendario<br />para generar análisis institucional
          </span>
          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
            Solo eventos con Actual + Forecast disponibles
          </span>
        </div>
      </div>
    )
  }

  const { loading, analysis, surprise, error } = state
  const cfg = LABEL_CONFIG[surprise?.surprise_label] || {}

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-header">
        <span className="panel-title">AI ANALYSIS — SMART MONEY</span>
        {surprise && (
          <span className="badge" style={{ background: cfg.bg, color: cfg.color, borderColor: `${cfg.color}44` }}>
            {cfg.label} · {surprise.surprise_pct > 0 ? '+' : ''}{surprise.surprise_pct?.toFixed(2)}%
          </span>
        )}
      </div>

      <div className="panel-body">
        {/* Event Header */}
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

        {/* Surprise Metrics */}
        {surprise && (
          <div style={{
            background: cfg.bg || 'var(--bg-card)',
            border: `1px solid ${cfg.color || 'var(--border)'}44`,
            borderRadius: 4, padding: '10px 12px', marginBottom: 10,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
              <span style={{ color: 'var(--text-dim)', fontSize: 11, letterSpacing: 1 }}>SURPRISE SCORE</span>
              <span style={{ color: cfg.color, fontWeight: 700 }}>
                {surprise.surprise_pct > 0 ? '+' : ''}{surprise.surprise_pct?.toFixed(2)}%
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>ASSET IMPACT SCORES</div>
            {surprise.asset_impacts && Object.entries(surprise.asset_impacts).map(([asset, val]) => (
              <ImpactBar key={asset} label={asset} value={val} />
            ))}
          </div>
        )}

        {/* AI Analysis */}
        {loading && (
          <div style={{ padding: 16, textAlign: 'center' }}>
            <div style={{ color: 'var(--green)', marginBottom: 8, fontSize: 12 }}>
              <span className="pulse">&#x25CF;</span> Generando análisis institucional...
            </div>
            <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>
              Claude claude-opus-4-8 · Smart Money methodology
            </div>
          </div>
        )}

        {error && (
          <div style={{ padding: 12, color: 'var(--red)', fontSize: 12, background: 'rgba(255,68,85,0.1)', borderRadius: 4 }}>
            Error: {error}
          </div>
        )}

        {analysis && !loading && (
          <div style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 4, padding: '12px',
          }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8, letterSpacing: 1 }}>
              ANÁLISIS INSTITUCIONAL · {analysis.model?.toUpperCase()} · {analysis.tokens_used} TOKENS
            </div>
            <AnalysisText text={analysis.analysis || ''} />
          </div>
        )}

        {!loading && !analysis && !error && event.actual == null && (
          <div style={{ padding: 16, color: 'var(--text-muted)', textAlign: 'center', fontSize: 12 }}>
            Este evento aún no tiene datos publicados (Actual = null)
          </div>
        )}
      </div>
    </div>
  )
}
