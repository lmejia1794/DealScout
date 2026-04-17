import React, { useState, useEffect, useRef } from 'react'
import { API_BASE } from '../config'

const POLL_INTERVAL_MS = 3000
const INITIAL_TIMEOUT_MS = 2500  // treat as cold if no response within this

export default function ServerWakeup({ children }) {
  // 'checking' | 'waking' | 'ready'
  const [status, setStatus] = useState('checking')
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef(Date.now())
  const timerRef = useRef(null)
  const pollRef = useRef(null)

  async function probe() {
    try {
      const ctrl = new AbortController()
      const timeout = setTimeout(() => ctrl.abort(), 2000)
      const res = await fetch(`${API_BASE}/health`, { signal: ctrl.signal })
      clearTimeout(timeout)
      if (res.ok) return true
    } catch {}
    return false
  }

  useEffect(() => {
    let cancelled = false

    async function init() {
      // Quick check — if server responds fast, skip the screen entirely
      const up = await probe()
      if (cancelled) return
      if (up) {
        setStatus('ready')
        return
      }

      // Server is cold-starting — show the wakeup screen and poll
      setStatus('waking')
      startRef.current = Date.now()

      timerRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
      }, 1000)

      pollRef.current = setInterval(async () => {
        const up = await probe()
        if (cancelled) return
        if (up) {
          clearInterval(pollRef.current)
          clearInterval(timerRef.current)
          setStatus('ready')
        }
      }, POLL_INTERVAL_MS)
    }

    init()

    return () => {
      cancelled = true
      clearInterval(timerRef.current)
      clearInterval(pollRef.current)
    }
  }, [])

  if (status === 'ready') return children

  if (status === 'checking') {
    // Invisible — avoids flash for warm servers
    return null
  }

  // status === 'waking'
  const dots = '.'.repeat((Math.floor(elapsed / 0.5) % 4))

  return (
    <div className="min-h-screen bg-[#0a1f12] flex flex-col items-center justify-center gap-8 px-6">

      {/* Animated rings */}
      <div className="relative flex items-center justify-center">
        <div className="absolute w-32 h-32 rounded-full border border-emerald-500/20 animate-ping [animation-duration:2.4s]" />
        <div className="absolute w-24 h-24 rounded-full border border-emerald-500/30 animate-ping [animation-duration:1.8s] [animation-delay:0.3s]" />
        <div className="w-14 h-14 rounded-full bg-emerald-900/60 border border-emerald-500/40 flex items-center justify-center">
          <svg className="w-6 h-6 text-emerald-400 animate-spin [animation-duration:2s]" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="2" />
            <path className="opacity-80" fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
          </svg>
        </div>
      </div>

      {/* Text */}
      <div className="text-center space-y-2">
        <p className="text-xs font-semibold text-emerald-500 tracking-widest uppercase">DealScout</p>
        <h1 className="text-2xl font-bold text-white">Server is starting up</h1>
        <p className="text-sm text-white/50 max-w-xs">
          The server spun down after inactivity. This usually takes 30–50 seconds on the free tier.
        </p>
      </div>

      {/* Elapsed + progress bar */}
      <div className="w-64 space-y-2">
        <div className="w-full h-1 bg-white/10 rounded-full overflow-hidden">
          <div
            className="h-full bg-emerald-500 rounded-full transition-all duration-1000"
            style={{ width: `${Math.min((elapsed / 50) * 100, 95)}%` }}
          />
        </div>
        <p className="text-center text-xs text-white/30">
          {elapsed}s elapsed — checking every {POLL_INTERVAL_MS / 1000}s
        </p>
      </div>

    </div>
  )
}
