import { useState, useEffect, useRef } from 'react'
import { api } from '../api/index.js'
import { useInterval } from '../hooks/useInterval.js'

const WEIGHT_COLOR = (w) => {
  if (w >= 9) return 'var(--red)'
  if (w >= 7) return 'var(--amber)'
  if (w >= 5) return 'var(--blue)'
  return 'var(--text-muted)'
}

const SIGNAL_STYLES = {
  'FUERTEMENTE ALCISTA USD':    { color: 'var(--green)', bg: 'rgba(0,212,170,0.12)' },
  'MODERADAMENTE ALCISTA USD':  { color: 'var(--green)', bg: 'rgba(0,212,170,0.07)' },
  'NEUTRAL':                    { color: 'var(--blue)',  bg: 'rgba(64,144,255,0.08)' },
  'MODERADAMENTE BAJISTA USD':  { color: 'var(--red)',   bg: 'rgba(255,68,85,0.07)' },
  'FUERTEMENTE BAJISTA USD':    { color: 'var(--red)',   bg: 'rgba(255,68,85,0.12)' },
}

function resolveSignalStyle(netSignal) {
  if (!netSignal) return SIGNAL_STYLES['NEUTRAL']
  const upper = netSignal.toUpperCase()
  const match = Object.entries(SIGNAL_STYLES).find(([k]) => upper.includes(k))
  return match?.[1] || SIGNAL_STYLES['NEUTRAL']
}

function ImpactBar({ label, value }) {
  const abs = Math.min(100, Math.abs(value))
  const pos = value >= 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
      <span style={{ width: 52, color: 'var(--text-dim)', fontSize: 11 }}>{label}</span>
      <div style={{ flex: 1, height: 6, background: 'var(--bg-primary)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: `${abs}%`,
          background: pos ? 'var(--green)' : 'var(--red)',
          borderRadius: 3,
          transition: 'width 0.5s ease',
          marginLeft: pos ? 0 : `${100 - abs}%`,
        }} />
      </div>
      <span style={{ width: 48, textAlign: 'right', color: pos ? 'var(--green)' : 'var(--red)', fontSize: 11 }}>
        {value > 0 ? '+' : ''}{value}
      </span>
    </div>
  )
}

function SurpriseBadge({ label }) {
  const map = {
    large_beat: { cls: 'badge-green', text: '▲▲ BEAT' },
    beat:       { cls: 'badge-green', text: '▲ BEAT' },
    in_line:    { cls: 'badge-blue',  text: '→ IN LINE' },
    miss:       { cls: 'badge-red',   text: '▼ MISS' },
    large_miss: { cls: 'badge-red',   text: '▼▼ MISS' },
  }
  const b = map[label]
  if (!b) return null
  return <span className={`badge ${b.cls}`} style={{ fontSize: 9, padding: '1px 4px' }}>{b.text}</span>
}

const SECTION_COLORS = {
  'NET SIGNAL:':             'var(--green)',
  'LECTURA CONSOLIDADA:':    'var(--blue)',
  'IMPACTO NETO:':           'var(--amber)',
  'CONTRADICCIONES':         'var(--red)',
  'ESCENARIO':               'var(--green)',
  'VISIÓN SMART MONEY:':     '#cc88ff',
  'VISION SMART MONEY:':     '#cc88ff',
}

function AnalysisText({ text }) {
  return (
    <div style={{ fontSize: 12, lineHeight: 1.7, color: 'var(--text-dim)' }}>
      {text.split('\n').map((line, i) => {
        const trimmed = line.trim()
        const color = Object.entries(SECTION_COLORS).find(([k]) =>
          trimmed.toUpperCase().startsWith(k.toUpperCase())
        )?.[1]
        const isHeader = Boolean(color) || /^[^\w]*[A-Z]{3,}.*:/.test(trimmed)
        return (
          <div key={i} style={{
            color:      isHeader ? (color || 'var(--text-primary)') : 'var(--text-dim)',
            fontWeight: isHeader ? 700 : 400,
            marginTop:  isHeader ? 10 : 0,
          }}>
            {line || ' '}
          </div>
        )
      })}
    </div>
  )
}

export default function ConsolidatedAnalysisPanel({ onActiveChange }) {
  const [data, setData] = useState(null)
  const activeRef = useRef(false)

  async function poll() {
    try {
      const result = await api.getConsolidatedAnalysis({ minutes: 45 })
      if (result.consolidated) {
        setData(result)
        if (!activeRef.current) {
          activeRef.current = true
          onActiveChange?.(true)
        }
      } else {
        if (activeRef.current) {
          activeRef.current = false
          onActiveChange?.(false)
          setData(null)
        }
      }
    } catch {
      // Silent fail — backend may not have events yet
    }
  }

  // Initial load on mount
  useEffect(() => { poll() }, [])
  // Poll every 30s thereafter
  useInterval(poll, 30_000)

  if (!data) return null

  const signalStyle = resolveSignalStyle(data.net_signal)

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-header">
        <span className="panel-title">
          ⚡ CONSOLIDATED — {data.event_count} SIMULTANEOUS RELEASES
        </span>
        {data.net_signal && (
          <span className="badge" style={{
            background: signalStyle.bg,
            color: signalStyle.color,
            borderColor: `${signalStyle.color}44`,
            fontSize: 9,
          }}>
            {data.net_signal}
          </span>
        )}
      </div>

      <div className="panel-body">
        {/* Simultaneous events list */}
        <div style={{
          background: 'var(--bg-card)', border: '1px solid var(--border)',
          borderRadius: 4, padding: '10px 12px', marginBottom: 10,
        }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 8 }}>
            SAME 5-MIN WINDOW — WEIGHTED BY INSTITUTIONAL IMPORTANCE
          </div>
          {(data.events || []).map((ev, i) => (
            <div key={i} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '5px 0',
              borderBottom: i < data.events.length - 1 ? '1px solid var(--border)' : 'none',
            }}>
              <span style={{
                fontSize: 9, fontWeight: 700,
                padding: '1px 5px', borderRadius: 2,
                background: 'rgba(0,0,0,0.3)',
                color: WEIGHT_COLOR(ev.weight),
                minWidth: 30, textAlign: 'center',
              }}>
                {ev.weight}/10
              </span>
              <span style={{ flex: 1, fontSize: 11, color: 'var(--text-primary)' }}>
                {ev.event_name}
              </span>
              <span style={{ fontSize: 11, color: 'var(--text-dim)', marginRight: 4 }}>
                {ev.actual ?? '–'}{ev.unit || ''}
              </span>
              <SurpriseBadge label={ev.surprise_label} />
            </div>
          ))}
        </div>

        {/* Weighted net impact bars */}
        {data.weighted_impacts && (
          <div style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 4, padding: '10px 12px', marginBottom: 10,
          }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 8 }}>
              WEIGHTED NET IMPACT SCORES
            </div>
            {Object.entries(data.weighted_impacts).map(([asset, val]) => (
              <ImpactBar key={asset} label={asset} value={val} />
            ))}
          </div>
        )}

        {/* Consolidated AI analysis */}
        {data.analysis && (
          <div style={{
            background: 'var(--bg-card)', border: '1px solid var(--border)',
            borderRadius: 4, padding: '12px',
          }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginBottom: 8, letterSpacing: 1 }}>
              ANÁLISIS CONSOLIDADO · {data.model?.toUpperCase()} · {data.tokens_used} TOKENS
            </div>
            <AnalysisText text={data.analysis} />
          </div>
        )}
      </div>
    </div>
  )
}
