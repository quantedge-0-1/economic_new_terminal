const LEVEL_STYLE = {
  strong:   { color: 'var(--red)',   bg: 'rgba(255,68,85,0.1)',   icon: '⚠️' },
  moderate: { color: 'var(--amber)', bg: 'rgba(255,170,0,0.08)',  icon: '⚡' },
  none:     { color: 'var(--green)', bg: 'rgba(0,212,170,0.06)',  icon: '✅' },
}

function AssetRow({ asset, info }) {
  const isDivergent = info.is_divergence
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '4px 0', borderBottom: '1px solid var(--border)',
    }}>
      <span style={{ width: 60, color: 'var(--text-dim)', fontSize: 11 }}>{asset}</span>
      <span style={{ fontSize: 11, color: 'var(--text-dim)' }}>
        Expected: <span style={{ color: info.expected_direction === 'alcista' ? 'var(--green)' : 'var(--red)' }}>
          {info.expected_direction === 'alcista' ? '▲' : '▼'} {info.expected_direction}
        </span>
      </span>
      <span style={{ fontSize: 11, color: info.actual_direction === 'alcista' ? 'var(--green)' : info.actual_direction === 'bajista' ? 'var(--red)' : 'var(--text-muted)' }}>
        Actual: {info.actual_direction === 'alcista' ? '▲' : info.actual_direction === 'bajista' ? '▼' : '→'} {info.actual_direction}
      </span>
      <span className={`badge ${isDivergent ? 'badge-red' : 'badge-green'}`} style={{ fontSize: 9 }}>
        {isDivergent ? `⚠ DIV ${info.divergence_strength?.toUpperCase()}` : '✓ CONFIRMA'}
      </span>
    </div>
  )
}

export default function DivergencePanel({ divergenceData, eventName }) {
  if (!divergenceData) {
    return (
      <div className="panel" style={{ flex: 1 }}>
        <div className="panel-header">
          <span className="panel-title">🔍 DIVERGENCE DETECTOR</span>
        </div>
        <div className="panel-body" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 8 }}>
          <span style={{ fontSize: 24 }}>🔍</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 11, textAlign: 'center' }}>
            Disponible tras analizar un evento con<br />datos de precio en tiempo real
          </span>
        </div>
      </div>
    )
  }

  const level = divergenceData.level || 'none'
  const style = LEVEL_STYLE[level] || LEVEL_STYLE.none

  return (
    <div className="panel" style={{ flex: 1 }}>
      <div className="panel-header">
        <span className="panel-title">🔍 DIVERGENCE DETECTOR</span>
        <span className="badge" style={{
          background: style.bg, color: style.color,
          borderColor: `${style.color}44`, fontSize: 10,
        }}>
          {style.icon} {divergenceData.has_divergence ? `${level.toUpperCase()} DIVERGENCE` : 'SIN DIVERGENCIA'}
        </span>
      </div>

      <div className="panel-body">
        {/* Event summary */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>EVENTO ANALIZADO</div>
          <div style={{ fontSize: 12, color: 'var(--text-primary)', fontWeight: 700 }}>{eventName}</div>
          <div style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 2 }}>
            Sorpresa: <span style={{ color: divergenceData.surprise_direction === 'beat' ? 'var(--green)' : 'var(--red)' }}>
              {divergenceData.surprise_direction?.toUpperCase()}
            </span>
          </div>
        </div>

        {/* SMC interpretation */}
        <div style={{
          background: style.bg, border: `1px solid ${style.color}33`,
          borderRadius: 4, padding: '8px 10px', marginBottom: 10,
          fontSize: 11, color: style.color, lineHeight: 1.6,
        }}>
          {divergenceData.message}
        </div>

        {/* Asset breakdown */}
        {divergenceData.assets && Object.keys(divergenceData.assets).length > 0 && (
          <div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: 1, marginBottom: 6 }}>ANÁLISIS POR ACTIVO</div>
            {Object.entries(divergenceData.assets).map(([asset, info]) => (
              <AssetRow key={asset} asset={asset} info={info} />
            ))}
          </div>
        )}

        {/* SMC global note */}
        {divergenceData.smc_interpretation && (
          <div style={{
            marginTop: 10, padding: '8px 10px',
            background: 'var(--bg-card)', borderRadius: 4,
            border: '1px solid var(--border)',
            fontSize: 11, color: 'var(--text-dim)', lineHeight: 1.6,
          }}>
            <div style={{ color: 'var(--text-muted)', fontSize: 10, marginBottom: 4, letterSpacing: 1 }}>VISIÓN SMART MONEY</div>
            {divergenceData.smc_interpretation}
          </div>
        )}
      </div>
    </div>
  )
}
