import React, { useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import ServiceMap from './ServiceMap'
import '../report.css'

const stripCitations = (text) => (text || '')
  .replace(/[【\[]\s*SRC:[^\]】]*[】\]]/gi, '')
  .replace(/\[cite:[^\]]*\]/gi, '')
  .trim()

// ---------------------------------------------------------------------------
// Citation processing — same logic as SectorBrief.jsx
// ---------------------------------------------------------------------------
function processCitations(text) {
  if (!text) return { processed: '', citations: [] }
  const citations = []
  const urlToIndex = {}
  let refCounter = 0
  const stripped = text.replace(/[【\[]\s*SRC:[^\]】]*$/, '').trimEnd()
  const processed = stripped.replace(/[【\[]SRC:\s*([^\]】]+)[】\]]/g, (match, source) => {
    source = source.trim()
    if (source.toLowerCase() === 'model_inference' || source.toLowerCase() === 'estimated') return ''
    if (source.startsWith('http://') || source.startsWith('https://')) {
      if (!urlToIndex[source]) {
        refCounter++
        urlToIndex[source] = refCounter
        citations.push({ index: refCounter, url: source })
      }
      return ` [${urlToIndex[source]}](${source})`
    }
    return ''
  })
  return { processed, citations }
}

const COUNTRY_FLAGS = {
  Germany: '🇩🇪', Austria: '🇦🇹', Switzerland: '🇨🇭',
  France: '🇫🇷', Netherlands: '🇳🇱', Belgium: '🇧🇪',
  Sweden: '🇸🇪', Norway: '🇳🇴', Denmark: '🇩🇰', Finland: '🇫🇮',
  Spain: '🇪🇸', Italy: '🇮🇹', Poland: '🇵🇱', UK: '🇬🇧',
  'United Kingdom': '🇬🇧', Portugal: '🇵🇹', Ireland: '🇮🇪',
  'Czech Republic': '🇨🇿', Romania: '🇷🇴', Hungary: '🇭🇺',
}

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
  // Render citation superscript links — shows the number, not the full URL
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className="text-blue-500 hover:text-blue-700 align-super text-[10px] font-semibold no-underline">
      {children}
    </a>
  ),
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

function fitBadgeClass(score) {
  if (score >= 8) return 'bg-green-100 text-green-800'
  if (score >= 5) return 'bg-yellow-100 text-yellow-700'
  return 'bg-red-100 text-red-600'
}

function dealTypeClass(type) {
  const t = (type || '').toLowerCase()
  if (t.includes('pe') || t.includes('buyout')) return 'bg-blue-100 text-blue-700'
  if (t.includes('strategic')) return 'bg-purple-100 text-purple-700'
  if (t.includes('growth')) return 'bg-green-100 text-green-700'
  return 'bg-gray-100 text-gray-600'
}

// ---------------------------------------------------------------------------
// Company block
// ---------------------------------------------------------------------------
function CompanyBlock({ company, profile, isLast }) {
  const flag = COUNTRY_FLAGS[company.country] || '🌍'
  const hqCountry = profile?.hq_country || company.country
  const serviceCountries = profile?.service_countries || [company.country]

  return (
    <div className={!isLast ? 'page-break mb-8' : 'mb-8'}>
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-xl font-bold text-gray-900">{flag} {company.name}</h2>
            {company.website && (
              <a href={company.website} target="_blank" rel="noopener noreferrer"
                className="text-xs text-blue-500 hover:underline shrink-0">
                {(() => { try { return new URL(company.website).hostname.replace(/^www\./, '') } catch { return 'Website' } })()} ↗
              </a>
            )}
          </div>
          <p className="text-sm text-gray-500">
            {[company.hq_city, company.country].filter(Boolean).join(', ')}
          </p>
        </div>
        <span className={`text-sm font-bold px-3 py-1 rounded-full ${fitBadgeClass(company.fit_score)}`}>
          {company.fit_score}/10
        </span>
      </div>

      {/* Meta pills */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        {company.ownership && (
          <span className="bg-emerald-50 text-emerald-700 border border-emerald-200 text-xs font-medium px-2 py-0.5 rounded-full">
            {stripCitations(company.ownership)}
          </span>
        )}
        {company.founded && (
          <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full">Founded {stripCitations(company.founded)}</span>
        )}
        {company.estimated_arr && (
          <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full">ARR {stripCitations(company.estimated_arr)}</span>
        )}
        {company.employee_count && (
          <span className="bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full">{stripCitations(company.employee_count)} employees</span>
        )}
      </div>

      <p className="text-sm text-gray-700 leading-relaxed mb-2">{stripCitations(company.description)}</p>
      <p className="text-xs text-gray-500 italic mb-3">{stripCitations(company.fit_rationale)}</p>

      {company.signals?.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-4">
          {company.signals.map((s, i) => (
            <span key={i} className="bg-purple-50 text-purple-700 text-xs px-2 py-0.5 rounded-full">{stripCitations(s)}</span>
          ))}
        </div>
      )}

      {/* Service map — only shown when full profile is loaded */}
      {profile ? (
        <div className="rounded-xl overflow-hidden mb-4 border border-gray-100">
          <ServiceMap hqCountry={hqCountry} serviceCountries={serviceCountries} />
        </div>
      ) : (
        <div className="mb-4 flex items-center gap-2">
          <span className="text-xs text-gray-500">HQ:</span>
          <span className="bg-gray-100 text-gray-700 text-xs font-medium px-2.5 py-1 rounded-full">
            {[company.hq_city, company.country].filter(Boolean).join(', ')}
          </span>
          <span className="text-xs text-gray-400 italic">— open Full Profile to load service map</span>
        </div>
      )}

      {/* Profile sections (if loaded) */}
      {profile && (
        <div className="space-y-4 mt-2">

          {/* Row 1: Business Model + Financials */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Business Model</h3>
              <ReactMarkdown components={MD}>{normalize(profile.business_model)}</ReactMarkdown>
            </div>
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Financial Snapshot</h3>
              <ReactMarkdown components={MD}>{normalize(profile.financials)}</ReactMarkdown>
            </div>
          </div>

          {/* Row 2: Competitive Positioning + Recent News */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Competitive Positioning</h3>
              <ReactMarkdown components={MD}>{normalize(profile.competitive_positioning)}</ReactMarkdown>
            </div>
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Recent News</h3>
              <ReactMarkdown components={MD}>{normalize(profile.recent_news)}</ReactMarkdown>
            </div>
          </div>

          {/* Fit Assessment — full width */}
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1">Fit Assessment</h3>
            <ReactMarkdown components={MD}>{normalize(profile.fit_assessment)}</ReactMarkdown>
          </div>

          {/* Decision Makers — full width, one card per person */}
          {profile.decision_makers?.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Key Contacts</h3>
              <div className="grid grid-cols-2 gap-2">
                {profile.decision_makers.map((dm, i) => (
                  <div key={i} className="bg-gray-50 border border-gray-100 rounded-lg px-3 py-2 text-xs space-y-0.5">
                    <p className="font-semibold text-gray-900">{stripCitations(dm.name)}</p>
                    <p className="text-gray-500">{stripCitations(dm.title)}</p>
                    {dm.notes && <p className="text-gray-400 italic">{stripCitations(dm.notes)}</p>}
                    <div className="flex flex-wrap gap-2 pt-0.5">
                      {dm.email && (
                        <a href={`mailto:${dm.email}`} className="text-blue-600 hover:underline">
                          {dm.email}
                        </a>
                      )}
                      {dm.linkedin_url && (
                        <a href={dm.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                          LinkedIn ↗
                        </a>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Comparables table (same as ComparablesPanel but print-safe, no expand)
// ---------------------------------------------------------------------------
function ComparablesTable({ transactions }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-gray-200 mb-8">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-200">
            {['Target', 'Acquirer', 'Year', 'Deal Type', 'EV', 'Multiple', 'Relevance'].map(h => (
              <th key={h} className="py-2 px-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {transactions.map((tx, i) => (
            <tr key={i} className="border-b border-gray-100">
              <td className="py-2 px-3 text-sm font-semibold text-gray-900">{stripCitations(tx.target)}</td>
              <td className="py-2 px-3 text-sm text-gray-600">{stripCitations(tx.acquirer)}</td>
              <td className="py-2 px-3 text-sm text-gray-500">{tx.year ?? '—'}</td>
              <td className="py-2 px-3 whitespace-nowrap">
                <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${dealTypeClass(tx.deal_type)}`}>
                  {stripCitations(tx.deal_type)}
                </span>
              </td>
              <td className="py-2 px-3 text-sm text-gray-600">{tx.reported_ev ?? '—'}</td>
              <td className="py-2 px-3 text-sm text-gray-600">{tx.reported_multiple ?? '—'}</td>
              <td className="py-2 px-3 text-xs text-gray-500">{stripCitations(tx.relevance)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// ReportView
// ---------------------------------------------------------------------------
const SESSION_KEY = 'dealscout_report'

export default function ReportView() {
  const { state } = useLocation()
  const navigate = useNavigate()
  const today = new Date().toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })

  // Persist report data in sessionStorage so Back navigation doesn't lose it
  useEffect(() => {
    if (state) {
      try { sessionStorage.setItem(SESSION_KEY, JSON.stringify(state)) } catch {}
    }
  }, [state])

  const reportData = state || (() => {
    try { return JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null') } catch { return null }
  })()

  if (!reportData) {
    return (
      <div className="min-h-screen flex items-center justify-center text-gray-500">
        <div className="text-center">
          <p className="mb-4">No report data. Go back and select companies or conferences first.</p>
          <button onClick={() => navigate('/')} className="text-blue-600 underline">← Back to DealScout</button>
        </div>
      </div>
    )
  }

  const {
    thesis,
    sectorBrief,
    selectedCompanies = [],
    selectedConferences = [],
    comparables = [],
    profiles = {},
  } = reportData

  return (
    <div className="min-h-screen bg-white">
      {/* Print button */}
      <div className="no-print fixed top-4 right-4 z-10 flex gap-2">
        <button
          onClick={() => navigate(-1)}
          className="text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg transition-colors"
        >
          ← Back
        </button>
        <button
          onClick={() => window.print()}
          className="text-sm bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors"
        >
          Print / Save as PDF
        </button>
      </div>

      <div className="max-w-4xl mx-auto px-8 py-10">

        {/* Cover block */}
        <div className="mb-8">
          <p className="text-xs font-semibold text-blue-600 tracking-widest uppercase mb-4">DealScout</p>
          <h1 className="text-3xl font-bold text-gray-900 mb-4">Sector Sourcing Report</h1>
          <div className="bg-blue-50 border-l-4 border-blue-400 px-5 py-4 rounded-r-xl mb-4">
            <p className="text-sm text-blue-900 italic">"{thesis}"</p>
          </div>
          <p className="text-xs text-gray-400">Generated {today}</p>
        </div>

        <hr className="border-gray-200 mb-8" />

        {/* Section 1 — Sector Brief */}
        {sectorBrief && (() => {
          const { processed, citations } = processCitations(normalize(sectorBrief))
          return (
            <div className="mb-8">
              <h2 className="text-lg font-bold text-gray-800 mb-3 pb-1 border-b border-gray-200">
                Sector Brief
              </h2>
              <ReactMarkdown components={MD}>{processed}</ReactMarkdown>
              {citations.length > 0 && (
                <div className="mt-4 pt-3 border-t border-gray-100">
                  <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1.5">Sources</p>
                  <div className="space-y-1">
                    {citations.map(({ index, url }) => {
                      const display = (() => { try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url } })()
                      return (
                        <div key={index} className="flex items-start gap-1.5 text-[10px] text-gray-400">
                          <span className="shrink-0 font-semibold text-gray-400">{index}</span>
                          <a href={url} target="_blank" rel="noopener noreferrer"
                            className="text-blue-400 hover:underline truncate">{display}</a>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )
        })()}

        {/* Section 2 — Selected Companies */}
        {selectedCompanies.length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-bold text-gray-800 mb-4 pb-1 border-b border-gray-200">
              Selected Companies
              <span className="text-sm font-normal text-gray-400 ml-2">({selectedCompanies.length})</span>
            </h2>
            {selectedCompanies.map((company, i) => (
              <CompanyBlock
                key={company.name}
                company={company}
                profile={profiles[company.name] || null}
                isLast={i === selectedCompanies.length - 1}
              />
            ))}
          </div>
        )}

        {/* Section 3 — Selected Conferences */}
        {selectedConferences.length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-bold text-gray-800 mb-4 pb-1 border-b border-gray-200">
              Selected Conferences
              <span className="text-sm font-normal text-gray-400 ml-2">({selectedConferences.length})</span>
            </h2>
            <div className="overflow-x-auto rounded-xl border border-gray-200">
              <table className="w-full text-left border-collapse">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200">
                    {['Name', 'Date', 'Location', 'Cost', 'Relevance'].map(h => (
                      <th key={h} className="py-2 px-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {selectedConferences.map((conf, i) => (
                    <tr key={i} className="border-b border-gray-100">
                      <td className="py-2.5 px-3 text-sm font-semibold text-gray-900">
                        {conf.website ? (
                          <a href={conf.website} target="_blank" rel="noopener noreferrer"
                            className="hover:underline text-gray-900">
                            {conf.name} ↗
                          </a>
                        ) : conf.name}
                      </td>
                      <td className="py-2.5 px-3 text-sm text-gray-600 whitespace-nowrap">{stripCitations(conf.date)}</td>
                      <td className="py-2.5 px-3 text-sm text-gray-600">{stripCitations(conf.location)}</td>
                      <td className="py-2.5 px-3 text-sm text-gray-600 whitespace-nowrap">{stripCitations(conf.estimated_cost)}</td>
                      <td className="py-2.5 px-3 text-xs text-gray-500">{stripCitations(conf.relevance)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Section 4 — Comparable Transactions */}
        {comparables.length > 0 && (
          <div className="mb-8">
            <h2 className="text-lg font-bold text-gray-800 mb-4 pb-1 border-b border-gray-200">
              Comparable Transactions
              <span className="text-sm font-normal text-gray-400 ml-2">({comparables.length})</span>
            </h2>
            <ComparablesTable transactions={comparables} />
          </div>
        )}

        {/* Section 5 — Appendix */}
        <div className="border-t border-gray-200 pt-6 mt-8">
          <p className="text-xs text-gray-400 italic">
            This report was generated by DealScout using AI-assisted research. All data should be
            independently verified before use in investment decisions.
          </p>
          <p className="text-xs text-gray-400 mt-1">Generated {today}</p>
        </div>

      </div>
    </div>
  )
}
