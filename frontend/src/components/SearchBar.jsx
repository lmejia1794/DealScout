import React, { useState, useEffect } from 'react'

const EXAMPLE_THESIS = 'Workforce management SaaS companies in DACH targeting mid-size manufacturers, €5–30M ARR'

export default function SearchBar({ onSearch, loading, hasResults, currentThesis }) {
  const [thesis, setThesis] = useState(currentThesis || EXAMPLE_THESIS)

  useEffect(() => {
    if (currentThesis !== undefined) setThesis(currentThesis)
  }, [currentThesis])

  const handleSubmit = () => {
    if (!thesis.trim() || loading) return
    onSearch(thesis)
  }

  return (
    <div className="space-y-3">
      <label className="block text-sm font-semibold text-gray-700">
        Investment Thesis
      </label>
      <textarea
        value={thesis}
        onChange={(e) => setThesis(e.target.value)}
        rows={3}
        className="w-full border border-gray-300 rounded-lg px-4 py-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        placeholder="Describe the sector, geography, and deal criteria..."
        disabled={loading}
      />

      <button
        onClick={handleSubmit}
        disabled={loading || !thesis.trim()}
        className="w-full sm:w-auto bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold py-2 px-6 rounded-lg transition-colors"
      >
        {hasResults ? 'Re-run Research' : 'Research'}
      </button>
    </div>
  )
}
