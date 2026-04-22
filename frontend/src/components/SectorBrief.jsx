import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import VerificationBadge from './VerificationBadge'
import LlmBadge from './LlmBadge'

// ---------------------------------------------------------------------------
// Citation processing — converts [SRC: ...] markers into numbered refs
// ---------------------------------------------------------------------------
function processCitations(text) {
  if (!text) return { processed: '', citations: [] }

  const citations = []       // { index, url, isReal }
  const urlToIndex = {}
  let refCounter = 0

  // Strip any incomplete citation at the very end (e.g. model hit token limit mid-marker)
  // Also strip Gemini's [cite: N] and mixed [cite: N, SRC: ...] markers that leak through
  const stripped = text
    .replace(/[【\[]\s*SRC:[^\]】]*$/, '')
    .replace(/\[cite:[^\]]*\]/gi, '')
    .trimEnd()

  const processed = stripped.replace(/[【\[]SRC:\s*([^\]】]+)[】\]]/g, (match, source) => {
    source = source.trim()
    if (source.toLowerCase() === 'model_inference') return ''
    if (source.toLowerCase() === 'estimated') return ''

    // Split by comma to handle multi-URL citations the model may emit
    const parts = source.split(/,\s*/)
    const refs = []
    for (const part of parts) {
      const url = part.trim()
      if (url.startsWith('http://') || url.startsWith('https://')) {
        if (!urlToIndex[url]) {
          refCounter++
          urlToIndex[url] = refCounter
          citations.push({ index: refCounter, url, isReal: true })
        }
        refs.push(` [${urlToIndex[url]}](${url})`)
      }
    }
    return refs.join('')
  })

  return { processed, citations }
}

// ---------------------------------------------------------------------------
// Markdown components
// ---------------------------------------------------------------------------
const MD_COMPONENTS = {
  h1: ({ children }) => <h1 className="text-lg font-bold text-gray-900 mt-6 mb-2">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-semibold text-gray-900 mt-5 mb-2 pb-1 border-b border-gray-200">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold text-gray-800 mt-4 mb-1">{children}</h3>,
  p:  ({ children }) => <p className="text-sm text-gray-700 leading-relaxed my-2">{children}</p>,
  strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
  em:     ({ children }) => <em className="italic text-gray-600">{children}</em>,
  ul: ({ children }) => <ul className="list-disc pl-5 my-2 space-y-1">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>,
  li: ({ children }) => <li className="text-sm text-gray-700 leading-relaxed">{children}</li>,
  blockquote: ({ children }) => <blockquote className="border-l-4 border-gray-200 pl-4 italic text-gray-500 my-3">{children}</blockquote>,
  code: ({ children }) => <code className="bg-gray-100 rounded px-1 text-sm font-mono text-gray-800">{children}</code>,
  pre:  ({ children }) => <pre className="bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-x-auto my-3 text-sm font-mono text-gray-800 whitespace-pre-wrap break-words">{children}</pre>,
  hr:   () => <hr className="border-gray-200 my-4" />,
  // Superscript citation links — consistent size for any digit count
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer"
      className="text-blue-500 hover:text-blue-700 no-underline font-semibold align-super text-[10px]" onClick={e => e.stopPropagation()}>
      {children}
    </a>
  ),
}

// Build context-aware component overrides for Key Questions section
function buildMDComponents() {
  let _inKeyQuestions = false

  return {
    ...MD_COMPONENTS,
    h2: ({ children }) => {
      const text = typeof children === 'string' ? children
        : Array.isArray(children) ? children.map(c => (typeof c === 'string' ? c : '')).join('') : ''
      _inKeyQuestions = text.toLowerCase().includes('key questions')

      const handleCopy = () => {
        navigator.clipboard.writeText(text).catch(() => {})
      }

      return (
        <h2 className="group flex items-center justify-between text-base font-semibold text-gray-900 mt-5 mb-2 pb-1 border-b border-gray-200">
          <span>{children}</span>
          <button
            onClick={handleCopy}
            className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-300 hover:text-gray-500 text-xs px-2 py-0.5 rounded"
            title="Copy section heading"
          >
            ⎘
          </button>
        </h2>
      )
    },
    ol: ({ children }) => {
      if (_inKeyQuestions) {
        return <ol className="list-decimal pl-5 my-3 space-y-3">{children}</ol>
      }
      return <ol className="list-decimal pl-5 my-2 space-y-1">{children}</ol>
    },
    li: ({ children }) => {
      if (_inKeyQuestions) {
        return (
          <li className="text-sm text-gray-800 leading-relaxed font-medium py-1 border-b border-gray-50 last:border-0">
            {children}
          </li>
        )
      }
      return <li className="text-sm text-gray-700 leading-relaxed">{children}</li>
    },
  }
}

function normalize(text) {
  return (text ?? '')
    .replace(/\\n/g, '\n')
    .replace(/\r\n/g, '\n')
    .trimStart()
    .replace(/^```[a-z]*\n?/i, '')
    .replace(/\n?```\s*$/, '')
    .trimStart()
}

// ---------------------------------------------------------------------------
// Citation footnotes section
// ---------------------------------------------------------------------------
function CitationFootnotes({ citations, verificationMap = {} }) {
  if (!citations?.length) return null
  const sup = (n) => String(n)  // plain number — styled consistently via CSS

  const isHallucinated = (v) =>
    v?.citation_note?.toLowerCase().includes('hallucinated') ||
    v?.citation_note?.toLowerCase().includes('does not exist')

  const isHomepageRedirect = (v, url) => {
    if (!v?.source_url || v.source_url === url) return false
    try {
      const orig = new URL(url)
      const final = new URL(v.source_url)
      const origPath = orig.pathname.replace(/\/$/, '')
      const finalPath = final.pathname.replace(/\/$/, '')
      return orig.hostname === final.hostname && origPath && (finalPath === '' || finalPath === '/')
    } catch { return false }
  }

  // Separate valid and invalid citations
  const validCitations = citations.filter(({ url }) => {
    const v = verificationMap[url]
    return !isHallucinated(v) && !isHomepageRedirect(v, url)
  })
  const invalidCitations = citations.filter(({ url }) => {
    const v = verificationMap[url]
    return isHallucinated(v) || isHomepageRedirect(v, url)
  })

  return (
    <div className="mt-4 pt-4 border-t border-gray-100 space-y-3">
      {validCitations.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Sources</p>
          <div className="space-y-1.5">
            {validCitations.map(({ index, url }) => {
              const v = verificationMap[url]
              const finalUrl = v?.source_url && v.source_url !== url ? v.source_url : url
              const isRedirect = v?.source_url && v.source_url !== url
              const displayUrl = (() => {
                try { return new URL(finalUrl).hostname.replace(/^www\./, '') + new URL(finalUrl).pathname.replace(/\/$/, '') }
                catch { return finalUrl }
              })()
              return (
                <div key={index} className="flex items-start gap-1.5 text-xs text-gray-500">
                  <span className="shrink-0 text-gray-400 font-semibold text-[10px]">{sup(index)}</span>
                  <div className="min-w-0">
                    <a href={finalUrl} target="_blank" rel="noopener noreferrer"
                      className="text-blue-400 hover:underline truncate block"
                      onClick={e => e.stopPropagation()}>
                      {displayUrl}
                    </a>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {invalidCitations.length > 0 && (
        <div className="bg-red-50 border border-red-100 rounded-lg px-3 py-2">
          <p className="text-[11px] font-semibold text-red-500 mb-1">
            ⚠ {invalidCitations.length} citation{invalidCitations.length > 1 ? 's' : ''} could not be verified — URL{invalidCitations.length > 1 ? 's' : ''} may be hallucinated
          </p>
          <div className="space-y-0.5">
            {invalidCitations.map(({ index, url }) => (
              <p key={index} className="text-[10px] text-red-400 font-mono truncate">
                {sup(index)} {url}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Verification summary
// ---------------------------------------------------------------------------
function VerificationSummary({ verification }) {
  const [open, setOpen] = useState(false)
  if (!verification?.claims?.length) return null

  const claims = verification.claims
  const counts = { verified: 0, contradicted: 0, inferred: 0, unverifiable: 0, pending: 0 }
  claims.forEach(({ verification: v }) => { const s = v?.status || 'pending'; counts[s] = (counts[s] || 0) + 1 })
  const hasContradicted = counts.contradicted > 0

  return (
    <div className="mt-4 border-t border-gray-100 pt-4">
      {hasContradicted && (
        <div className="mb-3 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5 text-xs text-amber-700 font-medium">
          ⚠ Some claims in this brief could not be verified — review before use
        </div>
      )}
      <button onClick={() => setOpen(o => !o)}
        className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700 transition-colors">
        <span className="font-semibold">Verification summary</span>
        <span className="flex gap-2 text-[11px]">
          {counts.verified > 0 && <span className="text-green-600">{counts.verified} verified</span>}
          {counts.contradicted > 0 && <span className="text-red-600">{counts.contradicted} contradicted</span>}
          {counts.inferred > 0 && <span className="text-amber-500">{counts.inferred} estimated</span>}
          {counts.unverifiable > 0 && <span className="text-gray-400">{counts.unverifiable} unverifiable</span>}
        </span>
        <span>{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div className="mt-3 space-y-3">
          {claims.map(({ claim, verification: v }, i) => (
            <div key={i} className="flex items-start gap-2">
              <VerificationBadge verification={v} fieldName="claim" />
              <div>
                <p className="text-xs text-gray-600">{claim}</p>
                {v?.corrected_value && v?.status === 'contradicted' && (
                  <p className="text-xs text-amber-700 mt-0.5">
                    ↻ Corrected: <strong>{v.corrected_value}</strong>
                    {v.source_url && (
                      <a href={v.source_url} target="_blank" rel="noopener noreferrer" className="ml-1 text-blue-500 hover:underline">
                        (source ↗)
                      </a>
                    )}
                  </p>
                )}
                {v?.source_snippet && v?.status !== 'contradicted' && (
                  <p className="text-[10px] text-gray-400 mt-0.5 italic">"{v.source_snippet}"</p>
                )}
                {v?.source_url && v?.status !== 'contradicted' && (
                  <a href={v.source_url} target="_blank" rel="noopener noreferrer" className="text-[10px] text-blue-400 hover:underline">
                    {v.source_url}
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function SectorBrief({ content, verification, llmMeta, regenerating, onRegenerate }) {
  const [collapsed, setCollapsed] = useState(false)

  const rawText = normalize(content)
  const { processed, citations } = processCitations(rawText)
  // Rebuild on each render so _inKeyQuestions closure state resets correctly
  const mdComponents = buildMDComponents()

  // Build url → verification map from sector_brief_verification claims
  // Used by CitationFootnotes to detect redirects and 404s
  const verificationMap = {}
  if (verification?.claims) {
    verification.claims.forEach(({ verification: v }) => {
      if (v?.citation_url) {
        verificationMap[v.citation_url] = v
      }
    })
  }

  return (
    <div className="bg-white border border-gray-200 rounded-xl shadow-sm">
      <div className="flex justify-between items-center px-6 py-4 cursor-pointer hover:bg-gray-50 transition-colors"
        onClick={() => setCollapsed(!collapsed)}>
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-lg font-bold text-gray-800">Sector Brief</h2>
          <LlmBadge meta={llmMeta} />
          {onRegenerate && (
            <button
              onClick={e => { e.stopPropagation(); onRegenerate() }}
              disabled={regenerating}
              className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 border border-gray-200 rounded-md px-2 py-0.5 bg-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {regenerating
                ? <><span className="w-3 h-3 border-2 border-gray-300 border-t-gray-600 rounded-full animate-spin" /> Regenerating…</>
                : '↻ Regenerate'}
            </button>
          )}
        </div>
        <button className="text-gray-400 hover:text-gray-600 text-sm font-medium shrink-0">
          {collapsed ? 'Expand ▾' : 'Collapse ▴'}
        </button>
      </div>

      {!collapsed && (
        <div className="px-6 pb-6">
          <ReactMarkdown components={mdComponents}>{processed}</ReactMarkdown>
          <CitationFootnotes citations={citations} verificationMap={verificationMap} />
          <VerificationSummary verification={verification} />
        </div>
      )}
    </div>
  )
}
