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
import { usePipeline } from './components/PipelineContext'
import { API_BASE } from './config'

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
  const reachedPhases = PIPELINE_STEPS.map(s =>
    logs.some(l => l.includes(s.marker))
  )
  const isDone = (i) => reachedPhases[i + 1] === true || (!loading && reachedPhases[i])
  const isActive = (i) => !isDone(i) && reachedPhases[i]

  const latestLog = [...logs].reverse().find(l => !l.startsWith('===') && l !== '— stopped by user —') || ''

  return (
    <div className="rounded-2xl overflow-hidden border border-gray-200 shadow-sm">
      {/* Header band */}
      <div className="bg-[#0d1f2d] px-5 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
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
  const scrollContainerRef = useRef(null)

  useEffect(() => {
    if (expanded && scrollContainerRef.current) {
      const el = scrollContainerRef.current
      el.scrollTop = el.scrollHeight
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
        <div ref={scrollContainerRef} className="bg-gray-950 px-4 py-3 max-h-72 overflow-y-auto font-mono text-xs">
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
  const { jobs, activeJobId, activeJob, addJob, cancelJob, selectJob, patchJobResults } = usePipeline()
  const { settings } = useSettings()
  const navigate = useNavigate()

  // Persistent saved searches (localStorage)
  const [savedSearches, setSavedSearches] = useState(loadSaved)
  // Viewing a saved search from localStorage (separate from live pipeline jobs)
  const [viewingSearch, setViewingSearch] = useState(null)

  // Per-session transient state — resets when active view changes
  const [selectedCompanies, setSelectedCompanies] = useState([])
  const [selectedConferences, setSelectedConferences] = useState([])
  const [comparables, setComparables] = useState(null)
  const [profiles, setProfiles] = useState({})
  const [tavilyCallsUsed, setTavilyCallsUsed] = useState(0)

  const [modalCompany, setModalCompany] = useState(null)
  const [preparingReport, setPreparingReport] = useState(false)

  // Track which job IDs have already been auto-saved to prevent duplicates
  const savedJobIds = useRef(new Set())

  // Reset per-session state when the active job or viewed search changes
  const prevActiveJobId = useRef(activeJobId)
  const prevViewingSearch = useRef(viewingSearch)
  useEffect(() => {
    const jobChanged = activeJobId !== prevActiveJobId.current
    const searchChanged = viewingSearch !== prevViewingSearch.current
    if (jobChanged || searchChanged) {
      prevActiveJobId.current = activeJobId
      prevViewingSearch.current = viewingSearch
      setSelectedCompanies([])
      setSelectedConferences([])
      setComparables(null)
      setProfiles({})
      setTavilyCallsUsed(0)
    }
  }, [activeJobId, viewingSearch])

  // Auto-save completed pipeline jobs to localStorage
  useEffect(() => {
    jobs.forEach(job => {
      if (job.status === 'done' && job.results && !savedJobIds.current.has(job.id)) {
        savedJobIds.current.add(job.id)
        const entry = {
          id: job.id,
          label: truncate(job.thesis, 60),
          thesis: job.thesis,
          ...job.results,
          comparables: null,
          saved_at: job.completedAt || new Date().toISOString(),
        }
        setSavedSearches(prev => {
          const updated = [entry, ...prev]
          saveToDisk(updated)
          return updated
        })
      }
    })
  }, [jobs])

  // Derive display state from active job (live) or viewed search (historical)
  const displayThesis = activeJob?.thesis || viewingSearch?.thesis || ''
  const displayResults = activeJob?.results || viewingSearch?.results || null
  const displayLogs = activeJob?.logs || []
  const displayLoading = !!activeJob && activeJob.status === 'running'
  const displayError = activeJob?.status === 'error' ? activeJob.error : null

  // Jobs currently running or queued — shown in sidebar
  const activePipelineJobs = jobs.filter(j => j.status === 'running' || j.status === 'queued')

  const autoSaveComparables = (txns) => {
    setSavedSearches(prev => {
      if (!prev.length) return prev
      const updated = [{ ...prev[0], comparables: txns }, ...prev.slice(1)]
      saveToDisk(updated)
      return updated
    })
  }

  const handleSearch = (thesis) => {
    setViewingSearch(null)
    addJob(thesis, settings)
  }

  const handleNew = () => {
    // Don't abort anything — running pipelines continue in the queue
    selectJob(null)
    setViewingSearch(null)
  }

  const handleUpdateVerification = (entityType, entityName, fieldName, newVerification) => {
    const listKey = entityType === 'company' ? 'companies' : 'conferences'
    const applyUpdate = (results) => {
      if (!results) return results
      const updated = (results[listKey] || []).map(item => {
        const raw = item?.company || item?.conference || item
        if (raw.name !== entityName) return item
        const base = item?.company ? item : { [entityType]: item, verifications: {}, overall_confidence: null }
        return { ...base, verifications: { ...base.verifications, [fieldName]: newVerification } }
      })
      return { ...results, [listKey]: updated }
    }

    if (activeJob) {
      patchJobResults(activeJob.id, applyUpdate)
    } else if (viewingSearch) {
      setViewingSearch(prev => prev ? { ...prev, results: applyUpdate(prev.results) } : prev)
    }
  }

  const handleSelectSavedSearch = (s) => {
    selectJob(null)
    setViewingSearch({
      thesis: s.thesis,
      results: {
        sector_brief: s.sector_brief,
        sector_brief_verification: s.sector_brief_verification || null,
        conferences: s.conferences,
        companies: s.companies,
      },
      comparables: s.comparables || null,
    })
    setComparables(s.comparables || null)
  }

  const handleSelectJob = (jobId) => {
    setViewingSearch(null)
    selectJob(jobId)
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
    autoSaveComparables(txns)
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

  const fetchProfileSilent = async (company) => {
    try {
      const resp = await fetch(`${API_BASE}/api/company/profile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company, thesis: displayThesis, settings }),
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
        thesis: displayThesis,
        sectorBrief: displayResults?.sector_brief || '',
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
          pipelineJobs={activePipelineJobs}
          activeJobId={activeJobId}
          onSelectJob={handleSelectJob}
          onCancelJob={cancelJob}
          onSelect={handleSelectSavedSearch}
          onDelete={handleDelete}
          onNew={handleNew}
        />
      </aside>

      {/* Main */}
      <main className="flex-1 p-5 md:p-8 max-w-4xl mx-auto w-full pb-24">
        <SearchBar
          onSearch={handleSearch}
          loading={displayLoading}
          hasResults={!!displayResults}
          currentThesis={displayThesis}
        />

        {/* Pipeline progress + logs */}
        {(displayLoading || displayLogs.length > 0) && (
          <div className="mt-6 space-y-3">
            {displayLoading && (
              <PipelineProgress
                logs={displayLogs}
                loading={displayLoading}
                onStop={() => activeJob && cancelJob(activeJob.id)}
              />
            )}
            <LogPanel logs={displayLogs} loading={displayLoading} />
          </div>
        )}

        {/* Error */}
        {displayError && !displayLoading && (
          <div className="mt-6 bg-red-50 border border-red-200 rounded-xl p-5">
            <p className="text-sm text-red-700 font-medium">Research failed</p>
            <p className="text-sm text-red-600 mt-1">{displayError}</p>
          </div>
        )}

        {/* Results — shown progressively as each phase completes */}
        {displayResults && (
          <div className="mt-8 space-y-8">
            {!displayLoading && (
              <ConfidenceSummaryBar
                results={displayResults}
                tavilyCallsUsed={tavilyCallsUsed}
                tavilyMax={settings.verification_tavily_max_calls || 20}
              />
            )}
            {displayResults.sector_brief && (
              <SectorBrief content={displayResults.sector_brief} verification={displayResults.sector_brief_verification} />
            )}
            {displayResults.conferences && (
              <ConferenceGrid
                conferences={displayResults.conferences}
                selectedConferences={selectedConferences}
                onToggleConference={toggleConference}
                conferencesContext={displayResults._conferences_context || ''}
                onUpdateVerification={(name, field, v) => handleUpdateVerification('conference', name, field, v)}
                sessionCapReached={tavilyCallsUsed >= (settings.verification_tavily_max_calls || 20)}
                onTavilyUsed={() => setTavilyCallsUsed(n => n + 1)}
              />
            )}
            {displayResults.companies && (
              <CompanyList
                companies={displayResults.companies}
                onViewProfile={setModalCompany}
                selectedCompanies={selectedCompanies}
                onToggleCompany={toggleCompany}
                companiesContext={displayResults._companies_context || ''}
                onUpdateVerification={(name, field, v) => handleUpdateVerification('company', name, field, v)}
                sessionCapReached={tavilyCallsUsed >= (settings.verification_tavily_max_calls || 20)}
                onTavilyUsed={() => setTavilyCallsUsed(n => n + 1)}
              />
            )}
            {!displayLoading && (
              <ComparablesPanel
                thesis={displayThesis}
                sectorBrief={displayResults.sector_brief}
                transactions={comparables}
                onLoaded={handleComparablesLoaded}
              />
            )}
          </div>
        )}
      </main>

      {/* Company deep-dive modal */}
      {modalCompany && (
        <CompanyModal
          company={modalCompany}
          thesis={displayThesis}
          comparables={comparables}
          initialProfile={profiles[modalCompany.name] || null}
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
