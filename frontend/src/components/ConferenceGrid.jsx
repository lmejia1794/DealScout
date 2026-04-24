import React, { useState } from 'react'
import VerificationBadge, { ConfidencePill } from './VerificationBadge'
import LlmBadge from './LlmBadge'

const stripCitations = (text) => (text || '')
  .replace(/[【\[]\s*SRC:[^\]】]*[】\]]/gi, '')
  .replace(/\[cite:[^\]]*\]/gi, '')
  .trim()

const MONTHS = ['january','february','march','april','may','june','july','august','september','october','november','december']
function parseDateOrder(dateStr) {
  if (!dateStr) return Infinity
  const lower = dateStr.toLowerCase()
  const monthIndex = MONTHS.findIndex(m => lower.includes(m))
  const yearMatch = dateStr.match(/\d{4}/)
  const year = yearMatch ? parseInt(yearMatch[0], 10) : 9999
  return year * 12 + (monthIndex >= 0 ? monthIndex : 0)
}

function CostBadge({ cost }) {
  const lower = cost?.toLowerCase() || ''
  let color = 'bg-gray-100 text-gray-600'
  if (lower === 'free') color = 'bg-green-100 text-green-700'
  else if (lower === 'unknown') color = 'bg-gray-100 text-gray-500'
  else color = 'bg-amber-100 text-amber-700'
  return (
    <span className={`shrink-0 inline-block max-w-[9rem] text-center text-xs font-semibold px-2.5 py-1 rounded-lg leading-snug ${color}`} title={cost}>
      {cost || 'Unknown'}
    </span>
  )
}

function normalizeItem(item) {
  if (item && item.conference) return item
  return { conference: item, verifications: {}, overall_confidence: null }
}

function ConferenceCard({ item, selected, onToggleSelect, conferencesContext, onUpdateVerification, onRemoveConference, sessionCapReached, onTavilyUsed }) {
  const { conference: conf, verifications, overall_confidence } = normalizeItem(item)
  const [showVerif, setShowVerif] = useState(false)

  const dlV = verifications.date_location
  const existenceV = verifications.existence
  const existenceContradicted = existenceV?.status === 'contradicted'

  // Auto-replace date_location if corrected
  const dateLocationCorrected = dlV?.status === 'contradicted' && dlV?.corrected_value && (!dlV?.human_override || dlV?.human_override === 'confirmed')
  const dateLocationDisputed = dlV?.human_override === 'disputed'

  const displayDateLocation = stripCitations(dateLocationCorrected && !dateLocationDisputed
    ? dlV.corrected_value
    : `${conf.date} · ${conf.location}`)
  const originalDateLocation = stripCitations(`${conf.date} · ${conf.location}`)

  const badgeProps = (fieldName) => ({
    entityName: conf.name,
    entityType: 'conference',
    fieldName,
    context: conferencesContext,
    onVerified: (v) => onUpdateVerification?.(conf.name, fieldName, v),
    onTavilyUsed,
    sessionCapReached,
  })

  return (
    <div className={`bg-white border rounded-xl p-5 shadow-sm flex flex-col gap-3 transition-colors ${selected ? 'border-blue-400 ring-1 ring-blue-200' : 'border-gray-200'}`}>
      {/* Existence warning */}
      {existenceContradicted && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 flex items-center justify-between gap-2">
          <p className="text-xs text-red-700 font-medium">⚠ Could not verify this event exists — treat with caution</p>
          {onRemoveConference && (
            <button onClick={() => onRemoveConference(conf.name)}
              className="text-xs text-red-600 hover:text-red-800 border border-red-300 px-2 py-0.5 rounded shrink-0">
              Remove
            </button>
          )}
        </div>
      )}

      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2 min-w-0">
          <input type="checkbox" checked={selected} onChange={onToggleSelect}
            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 cursor-pointer shrink-0" />
          <div className="min-w-0">
            <h3 className="font-semibold text-gray-900 text-sm leading-tight">{stripCitations(conf.name)}</h3>
            <div className="flex items-center gap-1 mt-0.5 flex-wrap">
              {dateLocationCorrected && !dateLocationDisputed ? (
                <>
                  <span className="text-xs text-gray-300 line-through">{originalDateLocation}</span>
                  <span className="text-xs text-gray-600 border-b border-amber-300">{displayDateLocation}</span>
                </>
              ) : (
                <span className="text-xs text-gray-500">{displayDateLocation}</span>
              )}
              {showVerif && dlV && (
                <VerificationBadge verification={dlV} fieldName="date_location" {...badgeProps('date_location')} />
              )}
              {showVerif && existenceV && !existenceContradicted && (
                <VerificationBadge verification={existenceV} fieldName="existence" {...badgeProps('existence')} />
              )}
              {verifications && Object.keys(verifications).length > 0 && (
                <button
                  onClick={() => setShowVerif(v => !v)}
                  className="text-[10px] text-gray-400 hover:text-gray-600 px-1.5 py-0.5 rounded border border-gray-200 hover:border-gray-300 transition-colors"
                >
                  {showVerif ? 'hide checks' : 'show checks'}
                </button>
              )}
            </div>
            {overall_confidence && <div className="mt-1"><ConfidencePill confidence={overall_confidence} verifications={verifications} /></div>}
          </div>
        </div>
        <CostBadge cost={conf.estimated_cost} />
      </div>

      <p className="text-xs text-gray-600 leading-relaxed">{stripCitations(conf.description)}</p>
      <p className="text-xs text-gray-500 italic">{stripCitations(conf.relevance)}</p>

      {conf.notable_attendees?.length > 0 && (
        <div className="flex flex-wrap gap-1 items-center">
          <span className="text-xs text-gray-400">Known to attend:</span>
          {conf.notable_attendees.map((a, i) => (
            <span key={i} className="bg-blue-50 text-blue-700 text-xs px-2 py-0.5 rounded-full">{a}</span>
          ))}
        </div>
      )}

      {conf.website ? (
        <a href={conf.website} target="_blank" rel="noopener noreferrer"
          className="self-start text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg transition-colors">
          Visit Website ↗
        </a>
      ) : (
        <span className="self-start text-xs text-gray-300">No website available</span>
      )}
    </div>
  )
}

export default function ConferenceGrid({
  conferences, selectedConferences = [], onToggleConference,
  conferencesContext = "", onUpdateVerification, sessionCapReached, onTavilyUsed, llmMeta,
  regenerating, onRegenerate,
}) {
  const [removed, setRemoved] = useState(new Set())

  if (!conferences?.length) {
    return (
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-sm text-amber-700">
        No conference data returned. Try refining your thesis or check your API keys.
      </div>
    )
  }

  const sorted = [...conferences]
    .filter(item => {
      const c = item?.conference || item
      return !removed.has(c.name)
    })
    .sort((a, b) => {
      const ca = a?.conference || a
      const cb = b?.conference || b
      return parseDateOrder(ca.date) - parseDateOrder(cb.date)
    })

  return (
    <div>
      <h2 className="flex items-center gap-2 flex-wrap text-lg font-bold text-gray-800 mb-4">
        Upcoming Conferences{' '}
        <span className="text-sm font-normal text-gray-400">
          ({sorted.length}{removed.size > 0 ? `, ${removed.size} removed` : ''})
        </span>
        <LlmBadge meta={llmMeta} />
        {onRegenerate && (
          <button
            onClick={onRegenerate}
            disabled={regenerating}
            className="inline-flex items-center gap-1 text-xs font-normal text-gray-400 hover:text-gray-700 border border-gray-200 rounded-md px-2 py-0.5 bg-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {regenerating
              ? <><span className="w-3 h-3 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" /> Regenerating…</>
              : '↻ Regenerate'}
          </button>
        )}
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {sorted.map((item, i) => {
          const conf = item?.conference || item
          return (
            <ConferenceCard
              key={i}
              item={item}
              selected={selectedConferences.some(s => s.name === conf.name)}
              onToggleSelect={() => onToggleConference?.(conf)}
              conferencesContext={conferencesContext}
              onUpdateVerification={onUpdateVerification}
              onRemoveConference={(name) => setRemoved(prev => new Set([...prev, name]))}
              sessionCapReached={sessionCapReached}
              onTavilyUsed={onTavilyUsed}
            />
          )
        })}
      </div>
    </div>
  )
}
