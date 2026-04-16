import React, { useState, useEffect, useCallback, useRef } from 'react'
import { API_BASE } from '../config'
import ReactMarkdown from 'react-markdown'
import ServiceMap from './ServiceMap'
import DecisionMakers from './DecisionMakers'
import OutreachDraft from './OutreachDraft'
import ComparablesPanel from './ComparablesPanel'
import { useSettings } from './SettingsContext'

// Reuse the same MD_COMPONENTS styling from SectorBrief
const MD = {
  h1: ({ children }) => <h1 className="text-base font-bold text-gray-900 mt-4 mb-1">{children}</h1>,
  h2: ({ children }) => <h2 className="text-sm font-semibold text-gray-900 mt-3 mb-1 pb-0.5 border-b border-gray-100">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold text-gray-800 mt-2 mb-0.5">{children}</h3>,
  p:  ({ children }) => <p  className="text-sm text-gray-700 leading-relaxed my-1.5">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
  em:     ({ children }) => <em className="italic text-gray-600">{children}</em>,
  ul: ({ children }) => <ul className="list-disc pl-4 my-1.5 space-y-0.5">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-4 my-1.5 space-y-0.5">{children}</ol>,
  li: ({ children }) => <li className="text-sm text-gray-700 leading-relaxed">{children}</li>,
  code: ({ children }) => <code className="bg-gray-100 rounded px-1 text-xs font-mono text-gray-800">{children}</code>,
}

function normalize(text) {
  return (text ?? '')
    .replace(/\\n/g, '\n')
    .replace(/\r\n/g, '\n')
    .trimStart()
    .replace(/^```[a-z]*\n?/i, '')
    .replace(/\n?```\s*$/, '')
    .trimStart()
}

function Section({ title, children }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">{title}</h3>
      {children}
    </div>
  )
}

function fitColor(score) {
  if (score >= 8) return 'bg-green-100 text-green-800'
  if (score >= 5) return 'bg-yellow-100 text-yellow-700'
  return 'bg-red-100 text-red-600'
}

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------
const PROFILE_STEPS = [
  { marker: 'Profile Generation', label: 'Deep profile' },
  { marker: 'Contact Enrichment', label: 'Contacts & enrichment' },
]

function LoadingView({ logs, company }) {
  const [logOpen, setLogOpen] = useState(false)
  const logRef = useRef(null)

  useEffect(() => {
    if (logOpen && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [logs, logOpen])

  const reached = PROFILE_STEPS.map(s => logs.some(l => l.includes(s.marker)))
  const activeIdx = reached.lastIndexOf(true)
  const isDone = (i) => reached[i + 1] === true || (!reached.some(Boolean) ? false : (i < activeIdx))
  const isActive = (i) => reached[i] && !isDone(i)

  const latestLog = [...logs].reverse().find(l => !l.startsWith('===')) || ''

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Branded header */}
      <div className="bg-[#0d2b1a] px-8 py-8 flex flex-col items-center gap-3 relative">
        {/* Ambient glow rings */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-48 h-48 rounded-full bg-emerald-500/5 animate-ping [animation-duration:3s]" />
          <div className="absolute w-32 h-32 rounded-full bg-emerald-500/8 animate-ping [animation-duration:2s] [animation-delay:0.5s]" />
        </div>
        <div className="relative z-10 flex flex-col items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-emerald-400 animate-pulse" />
          <h2 className="text-xl font-bold text-white">{company?.name}</h2>
          <p className="text-sm text-emerald-300/70">Generating deep profile…</p>
        </div>
      </div>

      {/* Steps */}
      <div className="px-10 py-6 flex-1 flex flex-col justify-center gap-6">
        <div className="space-y-3">
          {PROFILE_STEPS.map((step, i) => {
            const done = isDone(i)
            const active = isActive(i)
            const pending = !done && !active
            return (
              <div key={i} className="flex items-center gap-3">
                <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-all duration-500
                  ${done   ? 'bg-emerald-500 text-white' : ''}
                  ${active ? 'bg-blue-600 text-white ring-4 ring-blue-100' : ''}
                  ${pending ? 'bg-gray-100 text-gray-400' : ''}
                `}>
                  {done
                    ? <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
                    : <span>{i + 1}</span>
                  }
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`text-sm font-medium ${done ? 'text-emerald-700' : active ? 'text-blue-700' : 'text-gray-400'}`}>
                    {step.label}
                  </p>
                  {active && latestLog && (
                    <p className="text-xs text-gray-400 truncate mt-0.5">{latestLog}</p>
                  )}
                </div>
                {active && (
                  <div className="flex gap-0.5 shrink-0">
                    {[0, 1, 2].map(d => (
                      <div key={d} className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-bounce"
                        style={{ animationDelay: `${d * 0.15}s` }} />
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Collapsible log */}
        {logs.length > 0 && (
          <div className="border border-gray-100 rounded-lg overflow-hidden">
            <button
              onClick={() => setLogOpen(o => !o)}
              className="w-full flex items-center justify-between px-3 py-2 text-xs text-gray-400 hover:bg-gray-50 transition-colors"
            >
              <span>Pipeline details</span>
              <span>{logOpen ? '▴' : '▾'}</span>
            </button>
            {logOpen && (
              <div ref={logRef} className="bg-gray-950 px-3 py-2 max-h-40 overflow-y-auto font-mono text-xs">
                {logs.map((l, i) => (
                  <div key={i} className={l.startsWith('===') ? 'text-blue-400 font-semibold mt-1' : 'text-green-300'}>
                    {!l.startsWith('===') && <span className="text-gray-600 mr-1.5">›</span>}
                    {l}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Loaded state
// ---------------------------------------------------------------------------
function ProfileView({ company, profile, thesis, comparables, onClose }) {
  const location = [company.hq_city, company.country].filter(Boolean).join(', ')

  return (
    <div className="flex flex-col h-full overflow-y-auto">

      {/* Header */}
      <div className="bg-[#0d2b1a] px-8 py-6 relative">
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-white/50 hover:text-white text-2xl leading-none"
        >
          ✕
        </button>
        <div className="flex items-start justify-between pr-8">
          <div>
            <h2 className="text-2xl font-bold text-white">{company.name}</h2>
            <div className="flex flex-wrap gap-2 mt-2">
              {company.ownership && (
                <span className="text-xs bg-white/10 text-white/80 px-2.5 py-0.5 rounded-full">
                  {company.ownership}
                </span>
              )}
              <span className="text-xs text-white/60">{location}</span>
            </div>
          </div>
          <span className={`text-sm font-bold px-3 py-1 rounded-full mt-1 ${fitColor(company.fit_score)}`}>
            {company.fit_score}/10
          </span>
        </div>
      </div>

      {/* Service Map */}
      <div className="bg-[#0a2e1a] px-0">
        <ServiceMap
          serviceCountries={profile.service_countries || []}
          hqCountry={profile.hq_country || company.country}
        />
      </div>

      {/* Body */}
      <div className="flex-1 px-6 py-6">

        {/* Two-column content */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
          {/* Left column */}
          <div className="space-y-5">
            <Section title="Business Model">
              <ReactMarkdown components={MD}>{normalize(profile.business_model)}</ReactMarkdown>
            </Section>
            <Section title="Financial Snapshot">
              <ReactMarkdown components={MD}>{normalize(profile.financials)}</ReactMarkdown>
            </Section>
            <Section title="Recent News">
              <ReactMarkdown components={MD}>{normalize(profile.recent_news)}</ReactMarkdown>
            </Section>
          </div>

          {/* Right column */}
          <div className="space-y-5">
            <Section title="Competitive Positioning">
              <ReactMarkdown components={MD}>{normalize(profile.competitive_positioning)}</ReactMarkdown>
            </Section>
            <Section title="Fit Assessment">
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 mb-2 text-xs text-blue-700 italic">
                Thesis: {thesis}
              </div>
              <ReactMarkdown components={MD}>{normalize(profile.fit_assessment)}</ReactMarkdown>
            </Section>
            <Section title="Decision Makers">
              <DecisionMakers decisionMakers={profile.decision_makers || []} />
            </Section>
          </div>
        </div>

        {/* Comparables section */}
        <div className="border-t border-gray-200 pt-6 mb-6">
          {comparables ? (
            <ComparablesPanel
              thesis={thesis}
              sectorBrief=""
              transactions={comparables}
            />
          ) : (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">
                Comparable Transactions
              </h3>
              <p className="text-xs text-gray-400 italic">
                Load comparable transactions from the main results page to see them here.
              </p>
            </div>
          )}
        </div>

        {/* Outreach section */}
        <div className="border-t border-gray-200 pt-6">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">
            Outreach
          </h3>
          <OutreachDraft company={company} profile={profile} thesis={thesis} />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Modal shell
// ---------------------------------------------------------------------------
export default function CompanyModal({ company, thesis, comparables, initialProfile, onProfileLoaded, onClose }) {
  const [phase, setPhase] = useState(initialProfile ? 'loaded' : 'loading')
  const [logs, setLogs] = useState([])
  const [profile, setProfile] = useState(initialProfile || null)
  const [errorMsg, setErrorMsg] = useState('')
  const { settings } = useSettings()

  const fetchProfile = useCallback(async () => {
    setPhase('loading')
    setLogs([])
    setProfile(null)

    try {
      const resp = await fetch(`${API_BASE}/api/company/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company, thesis, settings }),
      })

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop()

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          let event
          try { event = JSON.parse(line.slice(6)) } catch { continue }

          if (event.type === 'log') {
            setLogs(prev => [...prev, event.message])
          } else if (event.type === 'result') {
            setProfile(event.data)
            setPhase('loaded')
            if (onProfileLoaded) onProfileLoaded(company.name, event.data)
          } else if (event.type === 'error') {
            setErrorMsg(event.message)
            setPhase('error')
          }
        }
      }
    } catch (e) {
      setErrorMsg(e.message || 'Something went wrong.')
      setPhase('error')
    }
  }, [company, thesis])

  useEffect(() => {
    if (!initialProfile) fetchProfile()
  }, [fetchProfile, initialProfile])

  // Close on Escape
  useEffect(() => {
    const handler = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-4xl bg-white shadow-2xl flex flex-col overflow-hidden my-0 md:my-6 md:rounded-2xl mx-auto">
        {/* Close button (always visible) */}
        {phase !== 'loaded' && (
          <button
            onClick={onClose}
            className="absolute top-4 right-4 z-20 text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ✕
          </button>
        )}

        {phase === 'loading' && <LoadingView logs={logs} company={company} />}

        {phase === 'error' && (
          <div className="flex flex-col items-center justify-center h-full gap-4 px-8 py-12">
            <p className="text-sm text-red-600">{errorMsg}</p>
            <button
              onClick={fetchProfile}
              className="text-sm bg-blue-600 text-white px-4 py-2 rounded-lg"
            >
              Retry
            </button>
          </div>
        )}

        {phase === 'loaded' && profile && (
          <ProfileView
            company={company}
            profile={profile}
            thesis={thesis}
            comparables={comparables}
            onClose={onClose}
          />
        )}
      </div>
    </div>
  )
}
