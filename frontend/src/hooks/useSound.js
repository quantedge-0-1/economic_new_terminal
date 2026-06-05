import { useCallback } from 'react'

function createTone(freq, duration, type = 'sine', gain = 0.3) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)()
    const osc = ctx.createOscillator()
    const gainNode = ctx.createGain()
    osc.connect(gainNode)
    gainNode.connect(ctx.destination)
    osc.frequency.value = freq
    osc.type = type
    gainNode.gain.setValueAtTime(gain, ctx.currentTime)
    gainNode.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration)
    osc.start(ctx.currentTime)
    osc.stop(ctx.currentTime + duration)
  } catch (e) {
    // Audio not available — silently skip
  }
}

export function useSound() {
  const playAlert = useCallback((level = 'high') => {
    if (level === 'critical') {
      // Three sharp beeps
      createTone(880, 0.15, 'square', 0.4)
      setTimeout(() => createTone(880, 0.15, 'square', 0.4), 200)
      setTimeout(() => createTone(1100, 0.3, 'square', 0.4), 400)
    } else if (level === 'high') {
      // Two medium beeps
      createTone(660, 0.15, 'sine', 0.3)
      setTimeout(() => createTone(880, 0.2, 'sine', 0.3), 200)
    } else {
      // One soft beep
      createTone(440, 0.2, 'sine', 0.2)
    }
  }, [])

  const playDataRelease = useCallback((isBeat) => {
    // Ascending chord for beat, descending for miss
    const freqs = isBeat ? [440, 550, 660] : [660, 550, 440]
    freqs.forEach((f, i) => setTimeout(() => createTone(f, 0.2, 'sine', 0.25), i * 100))
  }, [])

  return { playAlert, playDataRelease }
}
