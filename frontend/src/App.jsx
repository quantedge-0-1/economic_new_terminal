import { useState, useEffect } from 'react'
import Header from './components/Header.jsx'
import CalendarPanel from './components/CalendarPanel.jsx'
import AnalysisPanel from './components/AnalysisPanel.jsx'
import PricesPanel from './components/PricesPanel.jsx'
import AlertsPanel from './components/AlertsPanel.jsx'
import DivergencePanel from './components/DivergencePanel.jsx'
import SentimentPanel from './components/SentimentPanel.jsx'
import MemoryPanel from './components/MemoryPanel.jsx'
import PreReleasePanel from './components/PreReleasePanel.jsx'

export default function App() {
  const [selectedEvent, setSelectedEvent] = useState(null)
  const [surpriseData, setSurpriseData] = useState(null)
  const [backendOk, setBackendOk] = useState(false)
  const [alertCount, setAlertCount] = useState(0)

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch('/health')
        setBackendOk(res.ok)
      } catch {
        setBackendOk(false)
      }
    }
    check()
    const id = setInterval(check, 30_000)
    return () => clearInterval(id)
  }, [])

  function handleEventSelect(event) {
    setSelectedEvent(event)
    setSurpriseData(null)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh', fontFamily: 'var(--font-mono)' }}>
      <Header backendOk={backendOk} alertCount={alertCount} />

      {/* Pre-release scanner — auto-shows T-10 before any high-impact event */}
      <PreReleasePanel />

      {/* Main grid */}
      <div style={{
        display: 'flex',
        flex: 1,
        gap: 6,
        padding: 6,
        minHeight: 0,
        overflow: 'hidden',
      }}>
        {/* Left: Calendar */}
        <div style={{ flex: '0 0 340px', display: 'flex', overflow: 'hidden' }}>
          <CalendarPanel
            onEventSelect={handleEventSelect}
            selectedEvent={selectedEvent}
          />
        </div>

        {/* Center: AI Analysis */}
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          <AnalysisPanel
            event={selectedEvent}
            onSurpriseComputed={setSurpriseData}
          />
        </div>

        {/* Right: Prices */}
        <PricesPanel />
      </div>

      {/* Bottom row: Alerts + Divergence + Sentiment ISS + Event Memory */}
      <div style={{
        display: 'flex',
        gap: 6,
        padding: '0 6px 6px',
        height: 260,
        flexShrink: 0,
      }}>
        <AlertsPanel onAlertCount={setAlertCount} />
        <DivergencePanel
          divergenceData={surpriseData?.divergence || null}
          eventName={selectedEvent?.event_name}
        />
        <SentimentPanel event={selectedEvent} />
        <MemoryPanel event={selectedEvent} />
      </div>
    </div>
  )
}
