import React from 'react'

function LinkedInIcon() {
  return (
    <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 0 1-2.063-2.065 2.064 2.064 0 1 1 2.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
    </svg>
  )
}

function ConfidenceBadge({ level }) {
  if (!level) return null
  const styles = {
    high:   'bg-emerald-100 text-emerald-700',
    medium: 'bg-yellow-100 text-yellow-700',
    low:    'bg-gray-100 text-gray-500',
  }
  const labels = { high: 'Verified', medium: 'Likely', low: 'Unverified' }
  return (
    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded-full ${styles[level] || styles.low}`}>
      {labels[level] || level}
    </span>
  )
}

function sourceLabel(source) {
  const map = {
    website: 'Found on website',
    smtp_verified: 'SMTP verified',
    pattern_unverified: 'Pattern',
    web_search: 'Web search',
    web_search_completed: 'Completed from web',
  }
  return map[source] || source || ''
}

export default function DecisionMakers({ decisionMakers = [] }) {
  if (!decisionMakers.length) {
    return (
      <div className="text-sm text-gray-400 italic py-4 text-center">
        No decision makers identified for this company.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {decisionMakers.map((dm, i) => {
        const contact = dm.contact || {}
        const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(`${dm.name} ${dm.notes || ''} email contact`)}`

        return (
          <div key={i} className="p-3 bg-gray-50 rounded-lg space-y-2">
            {/* Name + title */}
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-gray-900">{dm.name}</p>
                <p className="text-xs text-gray-500">{dm.title}</p>
              </div>
              {dm.linkedin_url && (
                <a
                  href={dm.linkedin_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="shrink-0 flex items-center gap-1 text-xs bg-blue-50 hover:bg-blue-100 text-blue-700 px-2 py-1 rounded-lg transition-colors"
                >
                  <LinkedInIcon />
                  LinkedIn
                </a>
              )}
            </div>

            {dm.notes && (
              <p className="text-xs text-gray-400 italic">{dm.notes}</p>
            )}

            {/* Email row — single confident address */}
            {contact.email && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <a href={`mailto:${contact.email}`} className="text-blue-600 hover:underline font-mono">
                  {contact.email}
                </a>
                <ConfidenceBadge level={contact.email_confidence} />
                {contact.email_source && (
                  <span className="text-gray-400">{sourceLabel(contact.email_source)}</span>
                )}
              </div>
            )}

            {/* Email alternatives — multiple low-confidence candidates */}
            {!contact.email && contact.email_alternatives?.length > 0 && (
              <div className="space-y-1">
                <p className="text-[10px] text-gray-400 uppercase tracking-wide font-medium">Possible addresses</p>
                {contact.email_alternatives.map((alt, ai) => (
                  <div key={ai} className="flex flex-wrap items-center gap-1.5 text-xs">
                    <a href={`mailto:${alt.email}`} className="text-blue-600 hover:underline font-mono">
                      {alt.email}
                    </a>
                    <ConfidenceBadge level={alt.confidence} />
                    {alt.source && (
                      <span className="text-gray-400">{sourceLabel(alt.source)}</span>
                    )}
                  </div>
                ))}
              </div>
            )}

            {/* Phone row */}
            {contact.phone && (
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <a href={`tel:${contact.phone}`} className="text-blue-600 hover:underline font-mono">
                  {contact.phone}
                </a>
                <ConfidenceBadge level={contact.phone_confidence} />
                {contact.phone_source && (
                  <span className="text-gray-400">{sourceLabel(contact.phone_source)}</span>
                )}
              </div>
            )}

            {/* Enrichment notes (only when no contact found) */}
            {!contact.email && !contact.email_alternatives?.length && !contact.phone && contact.enrichment_notes && (
              <p className="text-[11px] text-gray-400 italic">{contact.enrichment_notes}</p>
            )}

            {/* Manual search escape hatch */}
            <div>
              <a
                href={searchUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[11px] text-gray-400 hover:text-blue-600 transition-colors"
              >
                Search web ↗
              </a>
            </div>
          </div>
        )
      })}
    </div>
  )
}
