import { useState, useRef } from 'react'
import { api } from '../api/index.js'
import { useInterval } from '../hooks/useInterval.js'

const ASSET_META = {
  XAUUSD: { label: 'GOLD',    symbol: 'XAU/USD', icon: '🥇', decimals: 2 },
  DXY:    { label: 'DXY',     symbol: 'USD INDEX',icon: '💵', decimals: 3 },
  US10Y:  { label: 'US10Y',   symbol: 'TLT (proxy)', icon: '📈', decimals: 2 },
  SPX:    { label: 'S&P 500', symbol: 'SPY (proxy)', icon: '📊', decimals: 2 },
}

function PriceCard({ symbol, data, prevData }) {
  const meta = ASSET_META[symbol] || { label: symbol, icon: '●', decimals: 2 }
  const price = data?.price
  const prevPrice = prevData?.price

  let change = null
  let pct = null
  if (price != null && prevPrice != null && prevPrice !== price) {
    change = price - prevPrice
    pct = (change / prevPrice) * 100
  }

  const color = change == null ? 'var(--text-primary)' : change >= 0 ? 'var(--green)' : 'var(--red)'
  const arrow = change == null ? '' : change >= 0 ? ' ▲' : ' ▼'

  return (
    <div style={{
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: 4,
      padding: '10px 12px',
      marginBottom: 6,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 2 }}>
            {meta.icon} {meta.label}
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{meta.symbol}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 18, fontWeight: 700, color, fontFamily: 'var(--font-mono)' }}>
            {price != null ? price.toFixed(meta.decimals) : '–'}
            <span style={{ fontSize: 12 }}>{arrow}</span>
          </div>
          {pct != null && (
            <div style={{ fontSize: 11, color }}>
              {pct > 0 ? '+' : ''}{pct.toFixed(3)}%
            </div>
          )}
        </div>
      </div>
      {data?.source && (
        <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 4, textAlign: 'right' }}>
          via {data.source}
        </div>
      )}
    </div>
  )
}

export default function PricesPanel() {
  const [prices, setPrices] = useState({})
  const [prevPrices, setPrevPrices] = useState({})
  const [lastUpdate, setLastUpdate] = useState(null)
  const [loading, setLoading] = useState(true)

  async function fetchPrices() {
    try {
      const data = await api.getLivePrices()
      setPrevPrices(prices)
      setPrices(data.prices || {})
      setLastUpdate(new Date())
    } catch (e) {
      console.error('Price fetch failed:', e)
    } finally {
      setLoading(false)
    }
  }

  useInterval(fetchPrices, 30_000)
  useState(() => { fetchPrices() }) // initial load

  const timeStr = lastUpdate
    ? lastUpdate.toLocaleTimeString('default', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    : '–'

  return (
    <div className="panel" style={{ width: 220, flexShrink: 0 }}>
      <div className="panel-header">
        <span className="panel-title">📡 LIVE PRICES</span>
        {!loading && (
          <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{timeStr}</span>
        )}
      </div>
      <div className="panel-body">
        {loading ? (
          <div style={{ color: 'var(--text-muted)', textAlign: 'center', padding: 16 }}>Loading...</div>
        ) : (
          Object.keys(ASSET_META).map(sym => (
            <PriceCard
              key={sym}
              symbol={sym}
              data={prices[sym]}
              prevData={prevPrices[sym]}
            />
          ))
        )}
        <div style={{ fontSize: 9, color: 'var(--text-muted)', textAlign: 'center', marginTop: 8 }}>
          Actualiza cada 30s · Twelve Data / yfinance
        </div>
      </div>
    </div>
  )
}
