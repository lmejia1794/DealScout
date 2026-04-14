import React, { useState, useEffect } from 'react'

const EXAMPLE_THESIS = 'Workforce management SaaS companies in DACH targeting mid-size manufacturers, €5–30M ARR'

export default function SearchBar({ onSearch, loading, hasResults, currentThesis }) {
  const [thesis, setThesis] = useState(currentThesis || EXAMPLE_THESIS)

  useEffect(() => {
    if (currentThesis !== undefined) setThesis(currentThesis)
  }, [currentThesis])
  const [knownRaw, setKnownRaw] = useState('')
  const [showKnown, setShowKnown] = useState(false)

  const handleSubmit = () => {
    if (!thesis.trim() || loading) return
    const known_companies = knownRaw
      .split('\n')
      .map(s => s.trim())
      .filter(Boolean)
    onSearch(thesis, known_companies)
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

      {/* Anchor companies — collapsible */}
      <div>
        <button
          type="button"
          onClick={() => setShowKnown(v => !v)}
          className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"
        >
          <span>{showKnown ? '▾' : '▸'}</span>
          <span>Known companies to include</span>
          {knownRaw.trim() && (
            <span className="bg-blue-100 text-blue-700 rounded-full px-1.5 py-0.5 leading-none">
              {knownRaw.split('\n').filter(s => s.trim()).length}
            </span>
          )}
        </button>
        {showKnown && (
          <div className="mt-2 space-y-1">
            <textarea
              value={knownRaw}
              onChange={e => setKnownRaw(e.target.value)}
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-400 focus:border-transparent text-gray-700 placeholder:text-gray-300"
              placeholder={"Boltrics\nShipnext\nCargowise"}
              disabled={loading}
            />
            <p className="text-xs text-gray-400">
              One company name per line — these will be force-included and scored, even if the model wouldn't have found them independently.
            </p>
          </div>
        )}
      </div>

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
