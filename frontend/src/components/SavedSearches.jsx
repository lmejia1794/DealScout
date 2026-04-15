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
        </ul>
      )}
    </div>
  )
}
