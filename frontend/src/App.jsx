import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import SearchBar from './components/SearchBar'
import SectorBrief from './components/SectorBrief'
import ConferenceGrid from './components/ConferenceGrid'
import CompanyList from './components/CompanyList'
import SavedSearches from './components/SavedSearches'
import SettingsDrawer from './components/SettingsDrawer'
import CompanyModal from './components/CompanyModal'
import ComparablesPanel from './components/ComparablesPanel'
import ReportActionBar from './components/ReportActionBar'
import { useSettings } from './components/SettingsContext'

const PHASES = [
  { marker: 'Step 0',  label: 'Discovering sources...' },
  { marker: 'Phase 1', label: 'Researching sector...' },
  { marker: 'Phase 2', label: 'Finding conferences...' },
  { marker: 'Phase 3', label: 'Building company list...' },
]

const LS_KEY = 'dealscout_searches'

function loadSaved() {
  try { return JSON.parse(localStorage.getItem(LS_KEY) || '[]') }
  catch { return [] }
}
function saveToDisk(searches) {
  localStorage.setItem(LS_KEY, JSON.stringify(searches))
}
function truncate(str, n) {
  return str.length > n ? str.slice(0, n - 1) + '…' : str
}

// ---------------------------------------------------------------------------
// Pipeline progress animation
// ---------------------------------------------------------------------------
const PIPELINE_STEPS = [
  { marker: 'Step 0',      label: 'Source Discovery', icon: '◈' },
  { marker: 'Phase 1',     label: 'Sector Research',  icon: '◈' },
  { marker: 'Phase 2',     label: 'Conference Intel', icon: '◈' },
  { marker: 'Phase 3',     label: 'Company Universe', icon: '◈' },
  { marker: 'Verification', label: 'Verification',    icon: '◈' },
]

function PipelineProgress({ logs, loading, onStop }) {
  // Determine which step is active / complete based on log history
  const reachedPhases = PIPELINE_STEPS.map(s =>
    logs.some(l => l.includes(s.marker))
  )
  // active = highest reached phase index
  const activeIdx = reachedPhases.lastIndexOf(true)
  // a phase is "done" if the next phase has been reached
  const isDone = (i) => reachedPhases[i + 1] === true || (!loading && reachedPhases[i])
  const isActive = (i) => !isDone(i) && reachedPhases[i]

  // Latest non-phase log line for the ticker
  const latestLog = [...logs].reverse().find(l => !l.startsWith('===') && l !== '— stopped by user —') || ''

  return (
    <div className="rounded-2xl overflow-hidden border border-gray-200 shadow-sm">
      {/* Header band */}
      <div className="bg-[#0d1f2d] px-5 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          {/* Animated radar pulse */}
          <div className="relative w-7 h-7 shrink-0">
            <div className="absolute inset-0 rounded-full bg-emerald-500/20 animate-ping" />
            <div className="absolute inset-1 rounded-full bg-emerald-500/30 animate-ping [animation-delay:0.3s]" />
            <div className="absolute inset-2 rounded-full bg-emerald-400" />
          </div>
          <div>
            <p className="text-xs font-semibold text-emerald-400 tracking-widest uppercase">Pipeline Running</p>
            <p className="text-[11px] text-gray-400 mt-0.5 font-mono truncate max-w-xs">{latestLog || '…'}</p>
          </div>
        </div>
        <button
          onClick={onStop}
          className="text-xs text-red-400 hover:text-red-300 border border-red-800 hover:border-red-600 px-3 py-1.5 rounded-lg transition-colors shrink-0"
        >
          Stop
        </button>
      </div>

      {/* Steps */}
      <div className="bg-white px-5 py-4">
        <div className="flex items-center gap-0">
          {PIPELINE_STEPS.map((step, i) => {
            const done = isDone(i)
            const active = isActive(i)
            const pending = !done && !active
            return (
              <React.Fragment key={i}>
                {/* Step node */}
                <div className="flex flex-col items-center gap-1.5 min-w-[90px]">
                  <div className={`
                    w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold transition-all duration-500
                    ${done    ? 'bg-emerald-500 text-white shadow-sm shadow-emerald-200' : ''}
                    ${active  ? 'bg-blue-600 text-white shadow-sm shadow-blue-200 ring-4 ring-blue-100' : ''}
                    ${pending ? 'bg-gray-100 text-gray-400' : ''}
                  `}>
                    {done
                      ? <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd"/></svg>
                      : <span>{i + 1}</span>
                    }
                  </div>
                  <span className={`text-[11px] font-medium text-center leading-tight
                    ${done ? 'text-emerald-600' : active ? 'text-blue-600' : 'text-gray-400'}
                  `}>
                    {step.label}
                    {active && <span className="block text-[10px] font-normal animate-pulse">running…</span>}
                    {done && <span className="block text-[10px] font-normal text-emerald-500">done</span>}
                  </span>
                </div>
                {/* Connector line */}
                {i < PIPELINE_STEPS.length - 1 && (
                  <div className="flex-1 h-0.5 mb-5 mx-1 rounded-full overflow-hidden bg-gray-100">
                    <div className={`h-full rounded-full transition-all duration-700 ${done ? 'w-full bg-emerald-400' : 'w-0 bg-blue-400'}`} />
                  </div>
                )}
              </React.Fragment>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Log panel component
// ---------------------------------------------------------------------------
function LogPanel({ logs, loading }) {
  const [expanded, setExpanded] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    if (expanded && bottomRef.current) {
      bottomRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, expanded])

  if (logs.length === 0 && !loading) return null

  return (
    <div className="border border-gray-200 rounded-xl overflow-hidden bg-white">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm text-gray-500 hover:bg-gray-50 transition-colors"
      >
        <span className="flex items-center gap-2">
          {loading && (
            <span className="w-3 h-3 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin inline-block" />
          )}
          <span className="font-medium text-gray-600">
            {loading ? 'Pipeline running' : 'Run logs'}
          </span>
          <span className="text-xs text-gray-400">({logs.length} messages)</span>
        </span>
        <span className="text-gray-400">{expanded ? '▴' : '▾'}</span>
      </button>

      {expanded && (
        <div className="bg-gray-950 px-4 py-3 max-h-72 overflow-y-auto font-mono text-xs">
          {logs.map((line, i) => {
            const isPhase = line.startsWith('===')
            const isError = line.startsWith('ERROR')
            const isStopped = line === '— stopped by user —'
            return (
              <div
                key={i}
                className={
                  isStopped
                    ? 'text-yellow-400 font-semibold mt-2'
                    : isPhase
                    ? 'text-blue-400 font-semibold mt-2 mb-0.5'
                    : isError
                    ? 'text-red-400'
                    : 'text-green-300'
                }
              >
                {!isPhase && !isStopped && <span className="text-gray-600 select-none mr-2">›</span>}
                {line}
              </div>
            )
          })}
          {loading && (
            <div className="text-gray-500 animate-pulse mt-1">› …</div>
          )}
          <div ref={bottomRef} />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Confidence summary bar (shows after verification pass)
// ---------------------------------------------------------------------------
function ConfidenceSummaryBar({ results, tavilyCallsUsed, tavilyMax }) {
  if (!results) return null
  const all = []
  const addVerifs = (verifs) => {
    if (!verifs) return
    Object.values(verifs).forEach(v => v?.status && all.push(v.status))
  }
  ;(results.sector_brief_verification?.claims || []).forEach(({ verification: v }) => v?.status && all.push(v.status))
  ;(results.companies || []).forEach(item => addVerifs(item?.verifications))
  ;(results.conferences || []).forEach(item => addVerifs(item?.verifications))

  if (!all.length) return null
  const counts = { verified: 0, contradicted: 0, inferred: 0, unverifiable: 0, pending: 0 }
  all.forEach(s => { counts[s] = (counts[s] || 0) + 1 })
  if (counts.verified + counts.contradicted + counts.inferred + counts.unverifiable === 0) return null

  const capReached = tavilyCallsUsed >= tavilyMax

  return (
    <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3 text-xs">
      <span className="font-semibold text-gray-500 uppercase tracking-wide text-[10px]">Research confidence</span>
      {counts.verified > 0 && <span className="text-green-600 font-medium">{counts.verified} verified</span>}
      {counts.contradicted > 0 && <span className="text-red-600 font-medium">{counts.contradicted} contradicted</span>}
      {counts.inferred > 0 && <span className="text-amber-500 font-medium">{counts.inferred} estimated</span>}
      {counts.unverifiable > 0 && <span className="text-gray-400">{counts.unverifiable} unverifiable</span>}
      {counts.pending > 0 && <span className="text-gray-300">{counts.pending} not checked</span>}
      <span className="ml-auto text-gray-400 text-[10px]">
        Tavily calls:{' '}
        <span className={capReached ? 'text-red-500 font-semibold' : 'text-gray-600 font-medium'}>
          {tavilyCallsUsed} / {tavilyMax}
        </span>
        {capReached && <span className="text-red-400 ml-1">(cap reached)</span>}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------
export default function App() {
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [phaseLabel, setPhaseLabel] = useState(PHASES[0].label)
  const [logs, setLogs] = useState([])
  const [savedSearches, setSavedSearches] = useState(loadSaved)
  const [currentThesis, setCurrentThesis] = useState('')
  const [modalCompany, setModalCompany] = useState(null)
  const [comparables, setComparables] = useState(null)      // null = not yet loaded
  const [selectedCompanies, setSelectedCompanies] = useState([])
  const [selectedConferences, setSelectedConferences] = useState([])
  const [profiles, setProfiles] = useState({})             // keyed by company name
  const [preparingReport, setPreparingReport] = useState(false)
  const [tavilyCallsUsed, setTavilyCallsUsed] = useState(0)
  const abortRef = useRef(null)
  const navigate = useNavigate()
  const { settings } = useSettings()

  // Derive phase label from latest log line
  useEffect(() => {
    const lastLog = logs[logs.length - 1] || ''
    for (const p of PHASES) {
      if (lastLog.includes(p.marker)) {
        setPhaseLabel(p.label)
        return
      }
    }
  }, [logs])

  const autoSave = (thesis, data, savedComparables) => {
    const entry = {
      id: crypto.randomUUID(),
      label: truncate(thesis, 60),
      thesis,
      ...data,
      comparables: savedComparables || null,
      saved_at: new Date().toISOString(),
    }
    setSavedSearches(prev => {
      const updated = [entry, ...prev]
      saveToDisk(updated)
      return updated
    })
  }

  const handleSearch = async (thesis, known_companies = []) => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setCurrentThesis(thesis)
    setResults(null)
    setError(null)
    setLogs([])
    setPhaseLabel(PHASES[0].label)
    setLoading(true)
    setComparables(null)
    setSelectedCompanies([])
    setSelectedConferences([])
    setProfiles({})

    try {
      const response = await fetch('/api/research', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thesis, known_companies, settings }),
        signal: controller.signal,
      })

      if (!response.ok) {
        const text = await response.text()
        throw new Error(text || `HTTP ${response.status}`)
      }

      const reader = response.body.getReader()
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
          try { event = JSON.parse(line.slice(6)) }
          catch { continue }

          if (event.type === 'log') {
            setLogs(prev => [...prev, event.message])
          } else if (event.type === 'result') {
            setResults(event.data)
            autoSave(thesis, event.data, null)
          } else if (event.type === 'error') {
            setError(event.message)
          }
        }
      }
    } catch (err) {
      if (err.name === 'AbortError') {
        setLogs(prev => [...prev, '— stopped by user —'])
      } else {
        setError(err.message || 'Something went wrong.')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleNew = () => {
    if (abortRef.current) abortRef.current.abort()
    setResults(null)
    setError(null)
    setLogs([])
    setCurrentThesis('')
    setComparables(null)
    setSelectedCompanies([])
    setSelectedConferences([])
    setProfiles({})
    setTavilyCallsUsed(0)
  }

  // Update a single verification field in results state (from on-demand verify)
  const handleUpdateVerification = (entityType, entityName, fieldName, newVerification) => {
    setResults(prev => {
      if (!prev) return prev
      const listKey = entityType === 'company' ? 'companies' : 'conferences'
      const itemKey = entityType === 'company' ? 'company' : 'conference'
      const updated = (prev[listKey] || []).map(item => {
        const raw = item?.[itemKey] || item
        if (raw.name !== entityName) return item
        const base = item?.[itemKey] ? item : { [itemKey]: item, verifications: {}, overall_confidence: null }
        return {
          ...base,
          verifications: { ...base.verifications, [fieldName]: newVerification },
        }
      })
      return { ...prev, [listKey]: updated }
    })
  }

  const handleSelect = (s) => {
    setCurrentThesis(s.thesis)
    // Support both new (sector_brief_verification) and old saved search shapes
    setResults({
      sector_brief: s.sector_brief,
      sector_brief_verification: s.sector_brief_verification || null,
      conferences: s.conferences,
      companies: s.companies,
    })
    setComparables(s.comparables || null)
    setError(null)
    setLogs([])
    setSelectedCompanies([])
    setSelectedConferences([])
    setProfiles({})
  }

  const handleDelete = (id) => {
    setSavedSearches(prev => {
      const updated = prev.filter(s => s.id !== id)
      saveToDisk(updated)
      return updated
    })
  }

  const handleComparablesLoaded = (txns) => {
    setComparables(txns)
    // Persist into the most recent saved search
    setSavedSearches(prev => {
      if (!prev.length) return prev
      const updated = [{ ...prev[0], comparables: txns }, ...prev.slice(1)]
      saveToDisk(updated)
      return updated
    })
  }

  const toggleCompany = (company) => {
    setSelectedCompanies(prev =>
      prev.some(c => c.name === company.name)
        ? prev.filter(c => c.name !== company.name)
        : [...prev, company]
    )
  }

  const toggleConference = (conf) => {
    setSelectedConferences(prev =>
      prev.some(c => c.name === conf.name)
        ? prev.filter(c => c.name !== conf.name)
        : [...prev, conf]
    )
  }

  // Fetch a profile silently (no UI) — used when building the report
  const fetchProfileSilent = async (company) => {
    try {
      const resp = await fetch('/api/company/profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company, thesis: currentThesis, settings }),
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
          if (event.type === 'result') return event.data
        }
      }
    } catch { /* ignore */ }
    return null
  }

  const handlePreviewReport = async () => {
    setPreparingReport(true)
    const updatedProfiles = { ...profiles }
    const missing = selectedCompanies.filter(c => !updatedProfiles[c.name])
    await Promise.all(
      missing.map(async (company) => {
        const profile = await fetchProfileSilent(company)
        if (profile) updatedProfiles[company.name] = profile
      })
    )
    setProfiles(updatedProfiles)
    setPreparingReport(false)
    navigate('/report', {
      state: {
        thesis: currentThesis,
        sectorBrief: results?.sector_brief || '',
        selectedCompanies,
        selectedConferences,
        comparables: comparables || [],
        profiles: updatedProfiles,
      },
    })
  }

  const handleModalClose = () => setModalCompany(null)

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      {/* Sidebar */}
      <aside className="w-full md:w-64 lg:w-72 bg-white border-b md:border-b-0 md:border-r border-gray-200 p-4 md:p-5 shrink-0 md:h-screen md:sticky md:top-0 md:overflow-y-auto">
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h1 className="text-xl font-bold text-blue-600">DealScout</h1>
            <p className="text-xs text-gray-400 mt-0.5">PE Deal Sourcing Copilot</p>
          </div>
          <SettingsDrawer />
        </div>
        <SavedSearches
          searches={savedSearches}
          onSelect={handleSelect}
          onDelete={handleDelete}
          onNew={handleNew}
        />
      </aside>

      {/* Main */}
      <main className="flex-1 p-5 md:p-8 max-w-4xl mx-auto w-full pb-24">
        <SearchBar
          onSearch={handleSearch}
          loading={loading}
          hasResults={!!results}
          currentThesis={currentThesis}
        />

        {/* Pipeline progress + logs */}
        {(loading || logs.length > 0) && (
          <div className="mt-6 space-y-3">
            {loading && (
              <PipelineProgress
                logs={logs}
                loading={loading}
                onStop={() => abortRef.current?.abort()}
              />
            )}
            <LogPanel logs={logs} loading={loading} />
          </div>
        )}

        {/* Error */}
        {error && !loading && (
          <div className="mt-6 bg-red-50 border border-red-200 rounded-xl p-5">
            <p className="text-sm text-red-700 font-medium">Research failed</p>
            <p className="text-sm text-red-600 mt-1">{error}</p>
          </div>
        )}

        {/* Results */}
        {results && !loading && (
          <div className="mt-8 space-y-8">
            <ConfidenceSummaryBar
              results={results}
              tavilyCallsUsed={tavilyCallsUsed}
              tavilyMax={settings.verification_tavily_max_calls || 20}
            />
            <SectorBrief content={results.sector_brief} verification={results.sector_brief_verification} />
            <ConferenceGrid
              conferences={results.conferences}
              selectedConferences={selectedConferences}
              onToggleConference={toggleConference}
              conferencesContext={results._conferences_context || ''}
              onUpdateVerification={(name, field, v) => handleUpdateVerification('conference', name, field, v)}
              sessionCapReached={tavilyCallsUsed >= (settings.verification_tavily_max_calls || 20)}
              onTavilyUsed={() => setTavilyCallsUsed(n => n + 1)}
            />
            <CompanyList
              companies={results.companies}
              onViewProfile={setModalCompany}
              selectedCompanies={selectedCompanies}
              onToggleCompany={toggleCompany}
              companiesContext={results._companies_context || ''}
              onUpdateVerification={(name, field, v) => handleUpdateVerification('company', name, field, v)}
              sessionCapReached={tavilyCallsUsed >= (settings.verification_tavily_max_calls || 20)}
              onTavilyUsed={() => setTavilyCallsUsed(n => n + 1)}
            />
            <ComparablesPanel
              thesis={currentThesis}
              sectorBrief={results.sector_brief}
              transactions={comparables}
              onLoaded={handleComparablesLoaded}
            />
          </div>
        )}
      </main>

      {/* Company deep-dive modal */}
      {modalCompany && (
        <CompanyModal
          company={modalCompany}
          thesis={currentThesis}
          comparables={comparables}
          onProfileLoaded={(name, profile) =>
            setProfiles(prev => ({ ...prev, [name]: profile }))
          }
          onClose={handleModalClose}
        />
      )}

      {/* Floating report action bar */}
      <ReportActionBar
        selectedCompanies={selectedCompanies}
        selectedConferences={selectedConferences}
        onClear={() => { setSelectedCompanies([]); setSelectedConferences([]) }}
        onPreviewReport={handlePreviewReport}
        preparingReport={preparingReport}
      />
    </div>
  )
}
