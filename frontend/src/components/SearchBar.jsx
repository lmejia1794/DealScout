import React, { useState, useRef, useEffect } from 'react'
import { EXAMPLES } from './WelcomePanel'

export default function SearchBar({ onSearch, loading, hasResults, currentThesis }) {
  const [thesis, setThesis] = useState(currentThesis || '')
  const [examplesOpen, setExamplesOpen] = useState(false)
  const dropdownRef = useRef(null)

  useEffect(() => {
    if (currentThesis !== undefined) setThesis(currentThesis)
  }, [currentThesis])

  useEffect(() => {
    if (!examplesOpen) return
    function handleClick(e) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setExamplesOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [examplesOpen])

  const handleSubmit = () => {
    if (!thesis.trim() || loading) return
    onSearch(thesis)
  }

  const handleSelectExample = (text) => {
    setThesis(text)
    setExamplesOpen(false)
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
        placeholder="Describe the sector, geography, and deal criteria — include ARR range, EV window, and ownership type for sharper results..."
        disabled={loading}
      />

      <div className="flex items-center gap-3">
        <button
          onClick={handleSubmit}
          disabled={loading || !thesis.trim()}
          className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white font-semibold py-2 px-6 rounded-lg transition-colors text-sm"
        >
          {hasResults ? 'Re-run Research' : 'Research'}
        </button>

        <div className="relative" ref={dropdownRef}>
          <button
            onClick={() => setExamplesOpen(o => !o)}
            disabled={loading}
            className="text-sm text-gray-400 hover:text-blue-600 transition-colors disabled:opacity-40"
          >
            Try an example ↓
          </button>

          {examplesOpen && (
            <div className="absolute left-0 top-7 z-50 w-96 bg-white border border-gray-200 rounded-xl shadow-lg overflow-hidden">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex.thesis}
                  onClick={() => handleSelectExample(ex.thesis)}
                  className="w-full text-left px-4 py-3 hover:bg-blue-50 border-b border-gray-100 last:border-0 transition-colors group"
                >
                  <span className="text-xs font-medium text-blue-600">{ex.label}</span>
                  <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{ex.thesis}</p>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
