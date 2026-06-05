import { useState, useEffect, useRef } from 'react'
import { api } from '../api/index.js'
import { useInterval } from '../hooks/useInterval.js'

// ── Color maps ────────────────────────────────────────────────────────────────

const STATE_COLORS = {
  ALREADY_DISCOUNTED_BULLISH:  '#ff4444',
  ALREADY_DISCOUNTED_BEARISH:  '#ff4444',
  CONSOLIDATION_ACCUMULATION:  '#f0c040',
  TRAP_SETUP_DETECTED:         '#ff8800',
  NOT_DISCOUNTED_NEUTRAL:      '#4090ff',
  INSUFFICIENT_DATA:           '#555555',
}

const ZONE_COLORS = {
  PREMIUM:     '#ff4444',
  EQUILIBRIUM: '#4090ff',
  DISCOUNT:    '#00d4aa',
}

const QUALITY_COLORS = {
  HIGH:   '#00d4aa',
  MEDIUM: '#ffaa00',
  LOW:    '#ff4444',
}

// ── Subcomponents ─────────────────────────────────────────────────────────────

function Countdown({ secondsInit }) {
  const [secs, setSecs] = useState(secondsInit)

  // Resync when API returns a fresh value
  useEffect(() => { setSecs(secondsInit) }, [secondsInit])

  // Local tick every second
  useEffect(() => {
    const id = setInterval(() => setSecs(s => Math.max(0, s - 1)), 1000)
    return () => clearInterval(id)
  }, [])

  const m = Math.floor(secs / 60)
  const s = secs % 60
  const urgent = secs <= 60

  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 36,
        fontWeight: 700,
        letterSpacing: 4,
        color: urgent ? '#ff4444' : '#f0c040',
        textShadow: urgent
          ? '0 0 20px #ff444466'
          : '0 0 16px #f0c04044',
        lineHeight: 1,
      }}>
        {String(m).padStart(2, '0')}:{String(s).padStart(2, '0')}
      </div>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 3, letterSpacing: 1 }}>
        {urgent ? '⚡ INMINENT' : 'T-MINUS'}
      </div>
    </div>
  )
}

function DiscountBar({ score }) {
  // score: -100 to +100. Center = 0. Right = bullish discounted, left = bearish.
  const abs = Math.abs(score)
  const bullish = score >= 0
  const color = abs >= 60 ? '#ff4444' : abs >= 30 ? '#f0c040' : '#4090ff'

  // The filled segment starts at center (50%) and extends toward the active side
  const barLeft  = bullish ? '50%' : `${50 - abs / 2}%`
  const barWidth = `${abs / 2}%`

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: 'var(--text-muted)', marginBottom: 3 }}>
        <span>◀ BAJISTA DESCONTADO</span>
        <span style={{ color, fontWeight: 700, fontSize: 11 }}>
          {score > 0 ? '+' : ''}{score}
        </span>
        <span>ALCISTA DESCONTADO ▶</span>
      </div>

      <div style={{ position: 'relative', height: 10, background: '#0d1521', borderRadius: 5, overflow: 'hidden', border: '1px solid #1e2d44' }}>
        <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: '#2a3f5f' }} />
        <div style={{
          position: 'absolute', top: 1, bottom: 1,
          left: barLeft, width: barWidth,
          background: `linear-gradient(90deg, ${color}88, ${color})`,
          borderRadius: 4,
          transition: 'left 0.8s ease, width 0.8s ease',
        }} />
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: '#333', marginTop: 2 }}>
        {['-100', '-50', '0', '+50', '+100'].map(v => <span key={v}>{v}</span>)}
      </div>
    </div>
  )
}

function ScoreBreakdown({ scores }) {
  const rows = [
    { label: 'Desplazamiento 35%', value: scores.displacement_score },
    { label: 'Sweep Liquidez 30%', value: scores.sweep_score },
    { label: 'Estructura 20%',     value: scores.structure_score },
    { label: 'Consolidación 15%',  value: scores.consolidation_score },
  ]
  return (
    <div style={{ marginTop: 6 }}>
      {rows.map(({ label, value }) => {
        const abs = Math.abs(value)
        const col = value > 10 ? '#00d4aa' : value < -10 ? '#ff4455' : '#4090ff'
        return (
          <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
            <span style={{ width: 130, fontSize: 9, color: 'var(--text-muted)' }}>{label}</span>
            <div style={{ flex: 1, height: 4, background: '#0d1521', borderRadius: 2, overflow: 'hidden', position: 'relative' }}>
              <div style={{ position: 'absolute', left: '50%', top: 0, bottom: 0, width: 1, background: '#1e2d44' }} />
              <div style={{
                position: 'absolute',
                top: 0, bottom: 0,
                left: value >= 0 ? '50%' : `${50 - abs / 2}%`,
                width: `${abs / 2}%`,
                background: col,
                borderRadius: 2,
              }} />
            </div>
            <span style={{ width: 36, textAlign: 'right', fontSize: 9, color: col }}>
              {value > 0 ? '+' : ''}{value}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function SignalGrid({ data }) {
  const dispColor = data.displacement_10m_pct > 0 ? '#00d4aa' : data.displacement_10m_pct < 0 ? '#ff4455' : 'var(--text-dim)'
  const zoneColor = ZONE_COLORS[data.price_zone] || 'var(--text-primary)'

  const rows = [
    {
      label: 'PRECIO ZONA',
      value: data.price_zone || '–',
      color: zoneColor,
    },
    {
      label: 'DESPLAZ. 10M',
      value: data.displacement_10m_pct != null
        ? `${data.displacement_10m_pct > 0 ? '+' : ''}${data.displacement_10m_pct.toFixed(3)}%`
        : 'sin datos',
      color: dispColor,
    },
    {
      label: 'BIAS ESTRUCTURA',
      value: data.directional_bias != null
        ? `${data.directional_bias > 0 ? '+' : ''}${data.directional_bias.toFixed(2)}`
        : '–',
      color: data.directional_bias > 0.3 ? '#00d4aa' : data.directional_bias < -0.3 ? '#ff4455' : 'var(--text-dim)',
    },
    {
      label: 'CONSOLIDANDO',
      value: data.is_consolidating ? 'SÍ — ACUMULACIÓN' : 'NO',
      color: data.is_consolidating ? '#f0c040' : 'var(--text-dim)',
    },
    {
      label: 'BSL SWEEP',
      value: data.bsl_swept ? '⚡ BARRIDO' : '–',
      color: data.bsl_swept ? '#ff8800' : 'var(--text-muted)',
    },
    {
      label: 'SSL SWEEP',
      value: data.ssl_swept ? '⚡ BARRIDO' : '–',
      color: data.ssl_swept ? '#ff8800' : 'var(--text-muted)',
    },
  ]

  return (
    <div>
      {rows.map(({ label, value, color }) => (
        <div key={label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <span style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: 0.5 }}>{label}</span>
          <span style={{ fontSize: 10, fontWeight: 600, color }}>{value}</span>
        </div>
      ))}

      {/* Key Levels */}
      <div style={{ borderTop: '1px solid var(--border)', paddingTop: 6, marginTop: 4 }}>
        <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 4 }}>NIVELES CLAVE</div>
        {[
          { label: 'BSL (máx 30m)',  value: data.bsl?.toFixed(2),        color: '#ff4444' },
          { label: 'EQUILIBRIO',     value: data.equilibrium?.toFixed(2), color: '#4090ff' },
          { label: 'SSL (mín 30m)',  value: data.ssl?.toFixed(2),         color: '#00d4aa' },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
            <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{label}</span>
            <span style={{ fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', color }}>
              {value ?? '–'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function AIAnalysis({ text }) {
  if (!text) return <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>Cargando análisis...</div>
  const lines = text.split('\n').filter(l => l.trim())
  return (
    <div>
      {lines.map((line, i) => {
        const isNumbered = /^[1-5]\./.test(line.trim())
        return (
          <div key={i} style={{
            fontSize: 10,
            lineHeight: 1.7,
            color: isNumbered ? 'var(--text-primary)' : 'var(--text-dim)',
            fontWeight: isNumbered ? 600 : 400,
            marginBottom: isNumbered ? 2 : 0,
          }}>
            {line}
          </div>
        )
      })}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function PreReleasePanel() {
  const [data, setData] = useState(null)

  async function fetchStatus() {
    try {
      const result = await api.getPreReleaseStatus()
      setData(result)
    } catch {
      // Silent fail — never break the terminal
    }
  }

  useEffect(() => { fetchStatus() }, [])
  useInterval(fetchStatus, 30_000)

  // Only render when active pre-release window is open
  if (!data || !data.active || data.phase !== 'PRE_RELEASE') return null

  const stateColor  = data.state_color || STATE_COLORS[data.institutional_state] || '#888'
  const qualColor   = QUALITY_COLORS[data.data_quality] || 'var(--text-muted)'

  return (
    <div style={{
      margin: '0 6px 6px',
      background: 'linear-gradient(135deg, #05080f 0%, #0a1525 100%)',
      border: `1px solid ${stateColor}44`,
      borderLeft: `3px solid ${stateColor}`,
      borderRadius: 4,
      padding: '10px 14px',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Animated scanning line */}
      <div className="scan-line" style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent 0%, ${stateColor}66 50%, transparent 100%)` }} />

      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10 }}>
        <span style={{
          fontSize: 9, fontWeight: 700, letterSpacing: 2,
          color: stateColor,
          animation: 'pulse 1.5s infinite',
        }}>
          ⚡ PRE-RELEASE SCANNER ACTIVO
        </span>

        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
          {data.event_name}
        </span>

        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>
          {data.currency} · F: {data.forecast ?? '–'}{data.unit || ''}  P: {data.previous ?? '–'}{data.unit || ''}
        </span>

        <span style={{ marginLeft: 'auto', fontSize: 9, color: qualColor, letterSpacing: 1 }}>
          DATOS: {data.data_quality}
          {data.history_depth_s > 0 && ` (${Math.round(data.history_depth_s / 60)}m)`}
        </span>
      </div>

      {/* 4-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '120px 220px 180px 1fr', gap: 14, alignItems: 'start' }}>

        {/* Col 1: Countdown */}
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
          <Countdown secondsInit={data.seconds_to_release} />
          <div style={{
            padding: '3px 10px',
            borderRadius: 3,
            background: `${stateColor}18`,
            border: `1px solid ${stateColor}44`,
            color: stateColor,
            fontSize: 9,
            fontWeight: 700,
            textAlign: 'center',
            letterSpacing: 0.5,
          }}>
            {data.state_label}
          </div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', textAlign: 'center', lineHeight: 1.5 }}>
            {data.smc_note}
          </div>
        </div>

        {/* Col 2: Discount Score */}
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 6 }}>
            INSTITUTIONAL DISCOUNT SCORE
          </div>
          <DiscountBar score={data.discount_score} />
          <ScoreBreakdown scores={{
            displacement_score: data.displacement_score,
            sweep_score:        data.sweep_score,
            structure_score:    data.structure_score,
            consolidation_score: data.consolidation_score,
          }} />
        </div>

        {/* Col 3: Signals + Key Levels */}
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 6 }}>
            SEÑALES PRE-RELEASE
          </div>
          <SignalGrid data={data} />
        </div>

        {/* Col 4: AI Analysis */}
        <div>
          <div style={{ fontSize: 9, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 6 }}>
            ANÁLISIS INSTITUCIONAL · CLAUDE HAIKU
          </div>
          <AIAnalysis text={data.ai_analysis} />
          <div style={{
            marginTop: 8,
            padding: '4px 8px',
            borderRadius: 3,
            background: `${stateColor}12`,
            border: `1px solid ${stateColor}30`,
            color: stateColor,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: 0.5,
          }}>
            ▶ {data.trader_action}
          </div>
        </div>
      </div>
    </div>
  )
}
