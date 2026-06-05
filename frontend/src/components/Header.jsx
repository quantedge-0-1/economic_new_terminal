import { useState, useEffect } from 'react'

function LiveClock() {
  const [time, setTime] = useState(new Date())
  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000)
    return () => clearInterval(id)
  }, [])
  const localTime = time.toLocaleTimeString('default', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  const localDate = time.toLocaleDateString('default', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })
  const tzAbbr    = time.toLocaleTimeString('en-US', { timeZoneName: 'short' }).split(' ').pop()
  const utcHM     = `${String(time.getUTCHours()).padStart(2,'0')}:${String(time.getUTCMinutes()).padStart(2,'0')}`
  const [hm, , ss] = localTime.split(':')
  return (
    <span style={{ color: 'var(--text-dim)', fontSize: 12 }}>
      <span style={{ color: 'var(--green)', marginRight: 4 }}>{tzAbbr}</span>
      {localDate} {hm}:{localTime.slice(3,5)}:<span style={{ color: 'var(--amber)' }}>{ss}</span>
      <span style={{ color: 'var(--text-muted)', fontSize: 10, marginLeft: 8 }}>UTC {utcHM}</span>
    </span>
  )
}

function SessionBadge() {
  const session = () => {
    const h = new Date().getUTCHours()
    if (h >= 8 && h < 12) return { label: 'LONDON', color: 'var(--blue)' }
    if (h >= 13 && h < 21) return { label: 'NEW YORK', color: 'var(--amber)' }
    if (h >= 0 && h < 4)  return { label: 'TOKYO', color: 'var(--purple)' }
    return { label: 'OFF SESSION', color: 'var(--text-muted)' }
  }
  const { label, color } = session()
  return (
    <span className="badge" style={{ background: `${color}22`, color, borderColor: `${color}44` }}>
      ● {label}
    </span>
  )
}

export default function Header({ backendOk, alertCount }) {
  return (
    <header style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '8px 16px',
      background: 'var(--bg-card)',
      borderBottom: '2px solid var(--border)',
      flexShrink: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: 'var(--green)', fontSize: 16, fontWeight: 700 }}>▶</span>
          <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)', letterSpacing: 1 }}>
            ECONOMIC TERMINAL
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1 }}>
            v1.0 · INSTITUTIONAL GRADE
          </span>
        </div>
        <SessionBadge />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <LiveClock />

        {alertCount > 0 && (
          <span className="badge badge-amber flash">
            ⚠ {alertCount} ALERTS
          </span>
        )}

        <span style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11 }}>
          <span className={backendOk ? 'pulse' : ''} style={{
            width: 6, height: 6, borderRadius: '50%',
            background: backendOk ? 'var(--green)' : 'var(--red)',
            display: 'inline-block',
          }} />
          <span style={{ color: backendOk ? 'var(--green)' : 'var(--red)' }}>
            {backendOk ? 'LIVE' : 'OFFLINE'}
          </span>
        </span>
      </div>
    </header>
  )
}
