import React from 'react'

export default function SavedSearches({ searches, draft, onSelect, onDelete, onNew }) {
  return (
    <div className="flex flex-col h-full">
      <button
        onClick={onNew}
        className="mb-4 w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-lg transition-colors"
      >
        + New Search
      </button>

      {!draft && searches.length === 0 ? (
        <p className="text-sm text-gray-400 text-center mt-4">No saved searches yet.</p>
      ) : (
        <ul className="space-y-2 overflow-y-auto flex-1">
          {/* In-progress draft — shown at top while research is running */}
          {draft && (
            <li
              className="bg-blue-50 border border-blue-200 rounded-lg p-3 cursor-pointer hover:border-blue-400 transition-colors"
              onClick={() => onSelect(draft)}
            >
              <div className="flex justify-between items-start gap-2">
                <span className="text-sm font-medium text-blue-800 line-clamp-2 flex-1">
                  {draft.label}
                </span>
                {draft.is_error ? (
                  <span className="text-[10px] font-semibold text-red-500 shrink-0">Failed</span>
                ) : (
                  <span className="flex items-center gap-1 shrink-0">
                    <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                    <span className="text-[10px] font-semibold text-blue-500">Researching</span>
                  </span>
                )}
              </div>
              <p className="text-[10px] text-blue-400 mt-1">
                {draft.companies?.length
                  ? `${draft.companies.length} companies found so far`
                  : 'Research in progress…'}
              </p>
            </li>
          )}

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
