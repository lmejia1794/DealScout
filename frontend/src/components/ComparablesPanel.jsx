import React, { useState, useRef, useEffect } from 'react'
import { API_BASE } from '../config'

function dealTypeClass(type) {
  const t = (type || '').toLowerCase()
  if (t.includes('pe') || t.includes('buyout')) return 'bg-blue-100 text-blue-700'
  if (t.includes('strategic')) return 'bg-purple-100 text-purple-700'
  if (t.includes('growth')) return 'bg-green-100 text-green-700'
  return 'bg-gray-100 text-gray-600'
}

function TransactionRow({ tx, expanded, onToggle }) {
  return (
    <>
      <tr
        className="border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors"
        onClick={onToggle}
      >
        <td className="py-2.5 px-3 text-sm font-semibold text-gray-900 whitespace-nowrap">
          {tx.target}
        </td>
        <td className="py-2.5 px-3 text-sm text-gray-600 whitespace-nowrap">{tx.acquirer}</td>
        <td className="py-2.5 px-3 text-sm text-gray-500 whitespace-nowrap">{tx.year ?? '—'}</td>
        <td className="py-2.5 px-3 whitespace-nowrap">
          <span className={`text-xs font-medium px-2 py-0.5 rounded-full whitespace-nowrap ${dealTypeClass(tx.deal_type)}`}>
            {tx.deal_type}
          </span>
        </td>
        <td className="py-2.5 px-3 text-sm text-gray-600 whitespace-nowrap">
          {tx.reported_ev ?? <span className="text-gray-400 italic">Undisclosed</span>}
        </td>
        <td className="py-2.5 px-3 text-sm text-gray-600 whitespace-nowrap">
          {tx.reported_multiple ?? <span className="text-gray-400 italic">Undisclosed</span>}
        </td>
        <td className="py-2.5 px-3 text-gray-400 text-xs">{expanded ? '▴' : '▾'}</td>
      </tr>
      {expanded && (
        <tr className="bg-blue-50/40 border-b border-gray-100">
          <td colSpan={7} className="px-4 py-3 text-xs text-gray-600 space-y-1">
            <p><span className="font-semibold text-gray-700">Target: </span>{tx.target_description}</p>
            <p><span className="font-semibold text-gray-700">Relevance: </span>{tx.relevance}</p>
          </td>
        </tr>
      )}
    </>
  )
}

// ---------------------------------------------------------------------------
// ComparablesPanel — used both on main results page and inside CompanyModal
// ---------------------------------------------------------------------------
export default function ComparablesPanel({ thesis, sectorBrief, transactions, onLoaded }) {
  const [phase, setPhase] = useState(transactions ? 'loaded' : 'loading') // loading | loaded | error
  const [logs, setLogs] = useState([])
  const [error, setError] = useState('')
  const [expandedIndex, setExpandedIndex] = useState(null)
  const abortRef = useRef(null)

  // If parent passes in pre-loaded transactions, stay in loaded state
  const displayTx = transactions || []

  const loadComparables = async () => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setPhase('loading')
    setLogs([])
    setError('')

    try {
      const resp = await fetch(`${API_BASE}/api/comparables`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ thesis, sector_brief: sectorBrief }),
        signal: controller.signal,
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

          if (event.type === 'log') {
            setLogs(prev => [...prev, event.message])
          } else if (event.type === 'result') {
            setPhase('loaded')
            if (onLoaded) onLoaded(event.data.transactions)
          } else if (event.type === 'error') {
            setError(event.message)
            setPhase('error')
          }
        }
      }
    } catch (e) {
      if (e.name !== 'AbortError') {
        setError(e.message || 'Something went wrong.')
        setPhase('error')
      }
    }
  }

  // Auto-load on mount if no transactions are pre-loaded
  useEffect(() => {
    if (!transactions && thesis) loadComparables()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (i) => setExpandedIndex(prev => prev === i ? null : i)

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-lg font-bold text-gray-800">
          Comparable Transactions
          {displayTx.length > 0 && (
            <span className="text-sm font-normal text-gray-400 ml-2">({displayTx.length})</span>
          )}
        </h2>
        {phase === 'error' && (
          <button
            onClick={loadComparables}
            className="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg transition-colors"
          >
            Retry
          </button>
        )}
      </div>

      {/* Loading log */}
      {phase === 'loading' && logs.length > 0 && (
        <div className="bg-gray-950 rounded-xl px-4 py-3 font-mono text-xs text-green-300 max-h-28 overflow-y-auto mb-4">
          {logs.map((l, i) => (
            <div key={i} className={l.startsWith('===') ? 'text-blue-400 font-semibold' : ''}>
              {!l.startsWith('===') && <span className="text-gray-600 mr-2">›</span>}
              {l}
            </div>
          ))}
        </div>
      )}

      {phase === 'error' && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700 mb-4">
          {error}
        </div>
      )}


{phase === 'loaded' && displayTx.length > 0 && (
        <div className="overflow-x-auto rounded-xl border border-gray-200">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-200">
                {['Target', 'Acquirer', 'Year', 'Deal Type', 'EV', 'Multiple', ''].map(h => (
                  <th key={h} className="py-2 px-3 text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {displayTx.map((tx, i) => (
                <TransactionRow
                  key={i}
                  tx={tx}
                  expanded={expandedIndex === i}
                  onToggle={() => toggle(i)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
