import React from 'react'

const STATUS_LABEL = {
  running: { text: 'Researching', color: 'text-blue-500', dot: 'bg-blue-500 animate-pulse' },
  queued:  { text: 'Queued',      color: 'text-amber-500', dot: 'bg-amber-400' },
}

export default function SavedSearches({
  searches,
  pipelineJobs = [],
  activeJobId,
  onSelectJob,
  onCancelJob,
  onSelect,
  onDelete,
  onNew,
}) {
  const hasAnything = pipelineJobs.length > 0 || searches.length > 0

  return (
    <div className="flex flex-col h-full">
      <button
        onClick={onNew}
        className="mb-4 w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg transition-colors"
      >
        + New Search
      </button>

      {!hasAnything ? (
        <p className="text-sm text-gray-400 text-center mt-4">No saved searches yet.</p>
      ) : (
        <ul className="space-y-2 overflow-y-auto flex-1">
          {/* Active pipeline jobs — running or queued */}
          {pipelineJobs.map((job) => {
            const s = STATUS_LABEL[job.status] || STATUS_LABEL.queued
            const isActive = job.id === activeJobId
            const companyCount = job.results?.companies?.length || 0
            return (
              <li
                key={job.id}
                onClick={() => onSelectJob(job.id)}
                className={`rounded-lg p-3 cursor-pointer transition-colors border ${
                  isActive
                    ? 'bg-blue-50 border-blue-400'
                    : 'bg-white border-blue-200 hover:border-blue-400'
                }`}
              >
                <div className="flex justify-between items-start gap-2">
                  <span className="text-sm font-medium text-blue-800 line-clamp-2 flex-1">
                    {job.thesis.length > 60 ? job.thesis.slice(0, 59) + '…' : job.thesis}
                  </span>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button
                      onClick={(e) => { e.stopPropagation(); onCancelJob(job.id) }}
                      className="text-gray-300 hover:text-red-400 text-xs transition-colors"
                      title="Cancel"
                    >
                      ✕
                    </button>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 mt-1.5">
                  <span className={`inline-block w-1.5 h-1.5 rounded-full ${s.dot}`} />
                  <span className={`text-[10px] font-semibold ${s.color}`}>{s.text}</span>
                  {companyCount > 0 && (
                    <span className="text-[10px] text-blue-400 ml-1">
                      · {companyCount} companies found
                    </span>
                  )}
                </div>
              </li>
            )
          })}

          {/* Divider between pipeline jobs and saved searches */}
          {pipelineJobs.length > 0 && searches.length > 0 && (
            <li className="pt-1 pb-0.5">
              <div className="border-t border-gray-100" />
            </li>
          )}

          {/* Saved searches */}
          {searches.map((s) => (
            <li
              key={s.id}
              className="bg-white border border-gray-200 rounded-lg p-3 group cursor-pointer hover:border-blue-400 transition-colors"
              onClick={() => onSelect(s)}
            >
              <div className="flex justify-between items-start gap-2">
                <span className="text-sm font-medium text-gray-800 line-clamp-2 flex-1">
                  {s.label}
                </span>
                <button
                  onClick={(e) => { e.stopPropagation(); onDelete(s.id) }}
                  className="text-gray-300 hover:text-red-400 text-xs shrink-0 transition-colors"
                  title="Delete"
                >
                  ✕
                </button>
              </div>
              <p className="text-xs text-gray-400 mt-1">
                {new Date(s.saved_at).toLocaleDateString('en-GB', {
                  day: 'numeric', month: 'short', year: 'numeric'
                })}
              </p>
            </li>
          ))}

          {/* CRM Tracker — coming soon, anchored below oldest saved search */}
          {searches.length > 0 && (
            <li className="pt-2 border-t border-gray-100 mt-1">
              <div className="flex items-center justify-between mb-1.5">
                <div className="flex items-center gap-1.5">
                  <svg className="w-3.5 h-3.5 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
                  </svg>
                  <span className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Contact Tracker</span>
                </div>
                <span className="text-[9px] font-semibold bg-amber-100 text-amber-600 px-1.5 py-0.5 rounded-full uppercase tracking-wide">
                  Soon
                </span>
              </div>
              <div className="bg-gray-50 border border-dashed border-gray-200 rounded-lg px-3 py-2.5 space-y-1.5 opacity-60">
                <p className="text-[11px] text-gray-500 leading-snug">
                  Log calls, emails, and follow-ups against enriched decision maker contacts across all saved searches.
                </p>
                <div className="flex flex-wrap gap-1">
                  {['Log call', 'Email sent', 'Follow-up', 'Meeting'].map(tag => (
                    <span key={tag} className="text-[10px] bg-white border border-gray-200 text-gray-400 px-1.5 py-0.5 rounded-full">
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}
