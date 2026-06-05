import { useState, useEffect, useRef } from 'react'
import { api } from '../api/index.js'
import { useInterval } from '../hooks/useInterval.js'
import { useSound } from '../hooks/useSound.js'

const LEVEL_CONFIG = {
  critical: { color: 'var(--red)',    bg: 'rgba(255,68,85,0.12)',   icon: '🔴' },
  high:     { color: 'var(--amber)',  bg: 'rgba(255,170,0,0.1)',    icon: '🟠' },
  medium:   { color: 'var(--blue)',   bg: 'rgba(64,144,255,0.08)',  icon: '🔵' },
  low:      { color: 'var(--text-muted)', bg: 'transparent',        icon: '⚪' },
}

function AlertRow({ alert, onRead }) {
  const cfg = LEVEL_CONFIG[alert.level] || LEVEL_CONFIG.low
  const time = new Date(alert.triggered_at).toLocaleTimeString('default', { hour: '2-digit', minute: '2-digit', hour12: false })

  return (
    <div
      onClick={() => !alert.is_read && onRead(alert.id)}
      style={{
        display: 'flex', gap: 8, padding: '6px 8px',
        borderBottom: '1px solid var(--border)',
        background: alert.is_read ? 'transparent' : cfg.bg,
        cursor: alert.is_read ? 'default' : 'pointer',
        opacity: alert.is_read ? 0.5 : 1,
        transition: 'opacity 0.2s',
      }}
    >
      <span style={{ fontSize: 12, marginTop: 1 }}>{cfg.icon}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 11, color: cfg.color, fontWeight: alert.is_read ? 400 : 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {alert.title}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 1 }}>
          {alert.alert_type?.replace(/_/g, ' ').toUpperCase()} · {time}
          {alert.currency && <span> · {alert.currency}</span>}
        </div>
      </div>
      {!alert.is_read && (
        <span style={{ fontSize: 9, color: cfg.color, alignSelf: 'center', whiteSpace: 'nowrap' }}>TAP TO DISMISS</span>
      )}
    </div>
  )
}

export default function AlertsPanel({ onAlertCount }) {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const prevUnread = useRef(0)
  const { playAlert } = useSound()

  async function fetchAlerts() {
    try {
      const data = await api.getAlerts({ limit: 30 })
      const items = data.alerts || []
      const unread = items.filter(a => !a.is_read).length

      if (unread > prevUnread.current && prevUnread.current >= 0) {
        const topLevel = items.find(a => !a.is_read)?.level || 'medium'
        playAlert(topLevel)
      }
      prevUnread.current = unread
      if (onAlertCount) onAlertCount(unread)
      setAlerts(items)
    } catch (e) {
      console.error('Alerts fetch failed:', e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAlerts() }, [])
  useInterval(fetchAlerts, 30_000)

  async function handleRead(id) {
    await api.markAlertRead(id)
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, is_read: true } : a))
    prevUnread.current = Math.max(0, prevUnread.current - 1)
    if (onAlertCount) onAlertCount(Math.max(0, prevUnread.current - 1))
  }

  const unreadCount = alerts.filter(a => !a.is_read).length

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-header">
        <span className="panel-title">⚡ ALERTS FEED</span>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          {unreadCount > 0 && (
            <span className="badge badge-amber">{unreadCount} NEW</span>
          )}
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{alerts.length} total</span>
        </div>
      </div>
      <div className="panel-body" style={{ padding: 0 }}>
        {loading ? (
          <div style={{ padding: 12, color: 'var(--text-muted)', textAlign: 'center' }}>Loading...</div>
        ) : alerts.length === 0 ? (
          <div style={{ padding: 12, color: 'var(--text-muted)', textAlign: 'center', fontSize: 11 }}>
            No alerts. Events must be released to trigger alerts.
          </div>
        ) : (
          alerts.map(a => <AlertRow key={a.id} alert={a} onRead={handleRead} />)
        )}
      </div>
    </div>
  )
}
