import React, { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import ServiceMap from './ServiceMap'
import DecisionMakers from './DecisionMakers'
import OutreachDraft from './OutreachDraft'
import ComparablesPanel from './ComparablesPanel'
import CompanyLogo from './CompanyLogo'

const stripCitations = (text) => (text || '')
  .replace(/[【\[]\s*SRC:[^\]】]*[】\]]/gi, '')
  .replace(/\[cite:[^\]]*\]/gi, '')
  .trim()

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

// Fixed-width skeleton rows — deterministic so they don't flicker on re-render
const SKELETON_LEFT = [
  ['w-20', 'w-full', 'w-5/6', 'w-full', 'w-4/5'],
  ['w-24', 'w-5/6', 'w-3/4', 'w-full'],
  ['w-16', 'w-full', 'w-4/5', 'w-5/6', 'w-2/3'],
]
const SKELETON_RIGHT = [
  ['w-28', 'w-full', 'w-4/5', 'w-5/6', 'w-3/4'],
  ['w-20', 'w-3/4', 'w-full', 'w-5/6'],
]

function SkeletonSection({ rows }) {
  const [label, ...lines] = rows
  return (
    <div className="space-y-2">
      <div className={`h-2.5 ${label} bg-gray-200 rounded-full animate-pulse mb-3`} />
      {lines.map((w, i) => (
        <div key={i} className={`h-2.5 ${w} bg-gray-100 rounded-full animate-pulse`}
          style={{ animationDelay: `${i * 80}ms` }} />
      ))}
    </div>
  )
}

function LoadingView({ logs, company, onStop }) {
  const [logOpen, setLogOpen] = useState(false)
  const logRef = useRef(null)

  useEffect(() => {
    if (logOpen && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [logs, logOpen])

  const reached = PROFILE_STEPS.map(s => logs.some(l => l.includes(s.marker)))
  const activeIdx = reached.lastIndexOf(true)
  const isDone  = (i) => reached[i + 1] === true || (!reached.some(Boolean) ? false : i < activeIdx)
  const isActive = (i) => reached[i] && !isDone(i)
  const latestLog = [...logs].reverse().find(l => !l.startsWith('===')) || ''

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Header */}
      <div className="bg-[#0d2b1a] px-8 py-8 flex flex-col items-center gap-2 relative overflow-hidden">
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-64 h-64 rounded-full bg-emerald-500/5 animate-ping [animation-duration:3s]" />
          <div className="absolute w-40 h-40 rounded-full bg-emerald-500/8 animate-ping [animation-duration:2s] [animation-delay:0.5s]" />
        </div>
        <div className="relative z-10 flex flex-col items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-emerald-400 animate-pulse" />
          <h2 className="text-2xl font-bold text-white">{company?.name}</h2>
          <p className="text-sm text-emerald-300/70">Generating deep profile…</p>
          {onStop && (
            <button
              onClick={onStop}
              className="mt-1 text-xs text-red-300 hover:text-red-200 border border-red-700/50 hover:border-red-500 px-3 py-1 rounded-lg transition-colors"
            >
              Stop
            </button>
          )}
        </div>
      </div>

      {/* Progress steps bar */}
      <div className="px-8 py-3 bg-gray-50 border-b border-gray-100 flex items-center gap-3">
        {PROFILE_STEPS.map((step, i) => {
          const done    = isDone(i)
          const active  = isActive(i)
          const pending = !done && !active
          return (
            <React.Fragment key={i}>
              <div className="flex items-center gap-2 shrink-0">
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold transition-all duration-500
                  ${done    ? 'bg-emerald-500 text-white' : ''}
                  ${active  ? 'bg-blue-600 text-white ring-4 ring-blue-100' : ''}
                  ${pending ? 'bg-gray-200 text-gray-400' : ''}
                `}>
                  {done
                    ? <svg className="w-3 h-3" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
                    : i + 1
                  }
                </div>
                <span className={`text-sm font-medium ${done ? 'text-emerald-700' : active ? 'text-blue-700' : 'text-gray-400'}`}>
                  {step.label}
                </span>
                {active && (
                  <div className="flex gap-0.5">
                    {[0, 1, 2].map(d => (
                      <div key={d} className="w-1 h-1 rounded-full bg-blue-400 animate-bounce"
                        style={{ animationDelay: `${d * 120}ms` }} />
                    ))}
                  </div>
                )}
              </div>
              {i < PROFILE_STEPS.length - 1 && (
                <div className={`flex-1 h-px ${done ? 'bg-emerald-300' : 'bg-gray-200'} transition-colors duration-500`} />
              )}
            </React.Fragment>
          )
        })}
        {latestLog && (
          <p className="ml-auto text-[11px] text-gray-400 truncate max-w-[220px] shrink-0">{latestLog}</p>
        )}
      </div>

      {/* Skeleton body — fills the empty space with a preview of what's coming */}
      <div className="flex-1 px-8 py-6 overflow-hidden">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Left column skeleton */}
          <div className="space-y-7">
            {SKELETON_LEFT.map((rows, i) => <SkeletonSection key={i} rows={rows} />)}
          </div>
          {/* Right column skeleton */}
          <div className="space-y-7">
            {SKELETON_RIGHT.map((rows, i) => <SkeletonSection key={i} rows={rows} />)}
            {/* Decision-maker skeleton cards */}
            <div className="space-y-2">
              <div className="h-2.5 w-32 bg-gray-200 rounded-full animate-pulse mb-3" />
              {[0, 1].map(j => (
                <div key={j} className="flex items-center gap-3 p-3 border border-gray-100 rounded-xl">
                  <div className="w-8 h-8 rounded-full bg-gray-200 animate-pulse shrink-0" />
                  <div className="flex-1 space-y-1.5">
                    <div className="h-2.5 w-2/5 bg-gray-200 rounded-full animate-pulse" />
                    <div className="h-2 w-1/3 bg-gray-100 rounded-full animate-pulse" />
                  </div>
                  <div className="h-6 w-16 bg-gray-100 rounded-lg animate-pulse" />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Collapsible log */}
      {logs.length > 0 && (
        <div className="border-t border-gray-100 overflow-hidden">
          <button
            onClick={() => setLogOpen(o => !o)}
            className="w-full flex items-center justify-between px-6 py-2.5 text-xs text-gray-400 hover:bg-gray-50 transition-colors"
          >
            <span>Pipeline details ({logs.length} messages)</span>
            <span>{logOpen ? '▴' : '▾'}</span>
          </button>
          {logOpen && (
            <div ref={logRef} className="bg-gray-950 px-4 py-2 max-h-32 overflow-y-auto font-mono text-xs">
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
          <div className="flex items-start gap-4">
            <CompanyLogo website={company.website} name={company.name} size="lg" />
            <div>
              <h2 className="text-2xl font-bold text-white">{company.name}</h2>
              <div className="flex flex-wrap gap-2 mt-2">
                {company.ownership && (
                  <span className="text-xs bg-white/10 text-white/80 px-2.5 py-0.5 rounded-full">
                    {stripCitations(company.ownership)}
                  </span>
                )}
                <span className="text-xs text-white/60">{location}</span>
                {company._registry_source && (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-green-50/20 text-green-300 border border-green-400/30">
                    ✓ {company._registry_source === 'companies_house' ? 'Companies House' : 'Wikidata'}
                  </span>
                )}
              </div>
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
            {profile.news?.length > 0 && (
              <Section title="Recent News">
                <div className="space-y-2">
                  {profile.news.map((article, i) => (
                    <a
                      key={i}
                      href={article.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block p-3 rounded-lg border border-gray-100 hover:border-blue-200 hover:bg-blue-50 transition-colors"
                    >
                      <p className="text-sm font-medium text-gray-800 leading-snug">{article.title}</p>
                      <p className="text-xs text-gray-500 mt-1">
                        {article.source} · {article.published_at?.slice(0, 10)}
                      </p>
                      {article.description && (
                        <p className="text-xs text-gray-600 mt-1 line-clamp-2">{article.description}</p>
                      )}
                    </a>
                  ))}
                </div>
              </Section>
            )}
            <Section title="Fit Assessment">
              <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2 mb-2 text-xs text-blue-700 italic">
                Thesis: {thesis}
              </div>
              <ReactMarkdown components={MD}>{normalize(profile.fit_assessment)}</ReactMarkdown>
            </Section>
            <Section title="Decision Makers">
              <DecisionMakers decisionMakers={profile.decision_makers || []} companyName={company.name} />
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
export default function CompanyModal({ company, thesis, comparables, profile, fetchState, onStop, onRetry, onClose }) {
  // Close on Escape
  useEffect(() => {
    const handler = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const phase = profile ? 'loaded' : fetchState?.phase || 'loading'

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-center">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />

      {/* Panel */}
      <div className="relative z-10 w-full max-w-4xl bg-white shadow-2xl flex flex-col overflow-hidden my-0 md:my-6 md:rounded-2xl mx-auto">
        {phase !== 'loaded' && (
          <button
            onClick={onClose}
            className="absolute top-4 right-4 z-20 text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ✕
          </button>
        )}

        {phase === 'loading' && <LoadingView logs={fetchState?.logs || []} company={company} onStop={onStop} />}

        {phase === 'error' && (
          <div className="flex flex-col items-center justify-center h-full gap-4 px-8 py-12">
            <p className="text-sm text-red-600">{fetchState?.error || 'Something went wrong.'}</p>
            <button
              onClick={onRetry}
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
