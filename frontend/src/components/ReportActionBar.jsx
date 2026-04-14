import React from 'react'

export default function ReportActionBar({
  selectedCompanies,
  selectedConferences,
  onClear,
  onPreviewReport,
  preparingReport,
}) {
  const count = selectedCompanies.length + selectedConferences.length
  if (count === 0) return null

  const label = [
    selectedCompanies.length > 0 && `${selectedCompanies.length} ${selectedCompanies.length === 1 ? 'company' : 'companies'}`,
    selectedConferences.length > 0 && `${selectedConferences.length} ${selectedConferences.length === 1 ? 'conference' : 'conferences'}`,
  ].filter(Boolean).join(' · ')

  return (
    <div className="fixed bottom-0 inset-x-0 z-40 flex justify-center pb-4 px-4 pointer-events-none">
      <div className="pointer-events-auto flex items-center gap-3 bg-gray-900 text-white rounded-2xl shadow-2xl px-5 py-3">
        <span className="text-sm font-medium text-gray-200">{label} selected</span>
        <button
          onClick={onPreviewReport}
          disabled={preparingReport}
          className="flex items-center gap-2 text-sm bg-blue-500 hover:bg-blue-400 disabled:opacity-60 text-white font-semibold px-4 py-1.5 rounded-lg transition-colors"
        >
          {preparingReport && (
            <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          )}
          {preparingReport ? 'Loading profiles…' : 'Preview Report'}
        </button>
        <button
          onClick={onClear}
          disabled={preparingReport}
          className="text-sm text-gray-400 hover:text-white disabled:opacity-40 transition-colors"
        >
          Clear
        </button>
      </div>
    </div>
  )
}
