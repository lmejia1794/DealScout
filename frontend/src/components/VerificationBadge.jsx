import React, { useState } from 'react'
import { useSettings } from './SettingsContext'
import { API_BASE } from '../config'

// Human-readable labels for field names
export const FIELD_LABELS = {
  existence:      'Company exists',
  ownership:      'Ownership status',
  founded:        'Founded year',
  estimated_arr:  'ARR estimate',
  employee_count: 'Employee count',
  website:        'Website',
  date_location:  'Date & location',
  date:           'Date',
  location:       'Location',
  estimated_cost: 'Ticket price',
  claim:          'Sector claim',
  claim_1:        'Market size',
  claim_2:        'Growth rate',
  claim_3:        'Key statistic',
}

// Fields eligible for auto-replace (corrected_value shown as primary)
const AUTO_REPLACE_FIELDS = new Set(['founded', 'ownership', 'employee_count', 'date_location', 'date', 'location'])

const STATUS_CONFIG = {
  verified:      { color: 'text-green-600',    bg: 'bg-green-50 border-green-200',     icon: '✓',  label: 'Verified',          dotColor: '#16a34a' },
  contradicted:  { color: 'text-red-600',      bg: 'bg-red-50 border-red-200',         icon: '✗',  label: 'Contradicted',      dotColor: '#dc2626' },
  corrected:     { color: 'text-amber-600',    bg: 'bg-amber-50 border-amber-300',     icon: '↻',  label: 'Corrected',         dotColor: '#d97706' },
  unverifiable:  { color: 'text-gray-400',     bg: 'bg-gray-50 border-gray-200',       icon: '?',  label: 'Unverifiable',      dotColor: '#9ca3af' },
  inferred:      { color: 'text-amber-500',    bg: 'bg-amber-50 border-amber-200',     icon: '~',  label: 'Estimated',         dotColor: '#f59e0b' },
  pending:       { color: 'text-gray-400',     bg: 'bg-gray-50 border-gray-300',       icon: '○',  label: 'Not checked',       dotColor: '#d1d5db' },
  loading:       { color: 'text-blue-400',     bg: 'bg-blue-50 border-blue-200',       icon: '…',  label: 'Checking…',         dotColor: '#60a5fa' },
  confirmed:     { color: 'text-emerald-700',  bg: 'bg-emerald-50 border-emerald-300', icon: '✓✓', label: 'Confirmed',         dotColor: '#047857' },
  disputed:      { color: 'text-rose-700',     bg: 'bg-rose-50 border-rose-200',       icon: '✗✗', label: 'Disputed',          dotColor: '#be123c' },
}

function getEffectiveStatus(verification) {
  if (!verification) return 'pending'
  if (verification.human_override) return verification.human_override
  if (verification.status === 'contradicted' && verification.corrected_value && AUTO_REPLACE_FIELDS.has(verification._fieldName)) {
    return 'corrected'
  }
  return verification.status || 'pending'
}

function domain(url) {
  try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url }
}

function Tooltip({ verification, fieldLabel, fieldName, isPending, canVerify, sessionCapReached, tavilyEnabled }) {
  const status = getEffectiveStatus({ ...verification, _fieldName: fieldName })
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending
  const label = fieldLabel || FIELD_LABELS[fieldName] || fieldName

  const isInference = verification?.citation_note === 'model_inference' || verification?.citation_note === 'estimated'
  const isHallucination = verification?.citation_note?.toLowerCase().includes('not exist') || verification?.citation_note?.toLowerCase().includes('hallucination')

  return (
    <div className="absolute bottom-full left-0 mb-1.5 z-50 w-72 bg-white border border-gray-200 rounded-xl shadow-xl overflow-hidden">
      {/* Header */}
      <div className={`px-3 py-2 flex items-center gap-2 border-b border-gray-100 ${
        status === 'verified' ? 'bg-green-50' :
        status === 'corrected' ? 'bg-amber-50' :
        status === 'contradicted' ? 'bg-red-50' :
        status === 'confirmed' ? 'bg-emerald-50' :
        status === 'disputed' ? 'bg-rose-50' : 'bg-gray-50'
      }`}>
        <span className={`text-sm font-bold ${cfg.color}`}>{cfg.icon}</span>
        <div>
          <span className={`text-xs font-semibold ${cfg.color}`}>{cfg.label}</span>
          {label && <span className="text-gray-400 text-xs ml-1">— {label}</span>}
        </div>
      </div>

      <div className="px-3 py-2.5 space-y-2 text-xs">
        {/* Snippet */}
        {verification?.source_snippet && !isInference && (
          <p className="text-gray-600 italic leading-snug">"{verification.source_snippet}"</p>
        )}

        {/* Inference explanation */}
        {isInference && (
          <p className="text-gray-500 leading-snug">
            {verification.citation_note === 'estimated'
              ? 'This value is estimated — no public data source was available.'
              : 'This value is based on model knowledge, not a verifiable source.'}
          </p>
        )}

        {/* Corrected value explanation */}
        {status === 'corrected' && verification?.corrected_value && (
          <p className="text-amber-700 leading-snug">
            Original AI value was contradicted. Displaying corrected value: <strong>{verification.corrected_value}</strong>
          </p>
        )}

        {/* Human override explanations */}
        {verification?.human_override === 'confirmed' && (
          <p className="text-emerald-700 text-[10px]">You accepted this correction.</p>
        )}
        {verification?.human_override === 'disputed' && verification?.corrected_value && (
          <p className="text-rose-700 text-[10px]">
            You reverted to the original value. Suggested correction: <em>{verification.corrected_value}</em>
          </p>
        )}

        {/* Tavily source */}
        {verification?.source_url && (
          <div className="flex items-center gap-1">
            <span className="text-gray-400 shrink-0">Tavily source:</span>
            <a href={verification.source_url} target="_blank" rel="noopener noreferrer"
              className="text-blue-500 hover:underline truncate font-medium" onClick={e => e.stopPropagation()}>
              {domain(verification.source_url)} ↗
            </a>
          </div>
        )}

        {/* Gemini citation */}
        {verification?.citation_url && (
          <div className="flex items-center gap-1">
            <span className="text-gray-400 shrink-0">Gemini cited:</span>
            <a href={verification.citation_url} target="_blank" rel="noopener noreferrer"
              className="text-blue-500 hover:underline truncate" onClick={e => e.stopPropagation()}>
              {domain(verification.citation_url)} ↗
            </a>
          </div>
        )}

        {/* Hallucination warning */}
        {isHallucination && (
          <p className="text-red-600 text-[10px] font-medium">⚠ {verification.citation_note}</p>
        )}

        {/* Non-hallucination citation note */}
        {verification?.citation_note && !isInference && !isHallucination && (
          <p className="text-gray-400 text-[10px]">{verification.citation_note}</p>
        )}

        {/* Pending CTA */}
        {isPending && (
          <p className={`text-[10px] font-medium ${canVerify ? 'text-blue-500' : 'text-gray-400'}`}>
            {sessionCapReached ? 'Session Tavily cap reached — increase limit in settings' :
             !tavilyEnabled ? 'Enable Tavily verification in settings to check this field' :
             'Click badge to verify (uses 1 Tavily credit)'}
          </p>
        )}

        {/* Override hint */}
        {!isPending && verification?.status !== 'pending' && (
          <p className="text-gray-300 text-[10px] border-t border-gray-100 pt-1.5">
            {!verification?.human_override
              ? verification?.corrected_value ? 'Click to accept correction' : 'Click to confirm or dispute'
              : verification.human_override === 'confirmed'
              ? 'Click to revert to original'
              : 'Click to reset'}
          </p>
        )}
      </div>
    </div>
  )
}

export default function VerificationBadge({
  verification,
  fieldLabel,
  fieldName,
  // On-demand verify props
  entityName,
  entityType,
  context,
  onVerified,
  onTavilyUsed,
  sessionCapReached,
}) {
  const { settings } = useSettings()
  const [localVerification, setLocalVerification] = useState(null)
  const [showTooltip, setShowTooltip] = useState(false)
  const [loadingField, setLoadingField] = useState(false)
  const [toast, setToast] = useState(null)

  const current = localVerification || verification
  const withField = current ? { ...current, _fieldName: fieldName } : null
  const isPending = !localVerification && (verification?.status === 'pending' || !verification)
  const tavilyEnabled = settings.verification_tavily_enabled !== false
  const canVerify = isPending && tavilyEnabled && !sessionCapReached && !loadingField

  const effectiveStatus = loadingField ? 'loading' : getEffectiveStatus(withField || { status: 'pending' })
  const cfg = STATUS_CONFIG[effectiveStatus] || STATUS_CONFIG.pending

  const handleClick = async (e) => {
    e.stopPropagation()
    if (isPending) {
      if (!canVerify) return
      const claim = current?.claim || verification?.claim
      if (!claim || !fieldName || !entityName) return
      setLoadingField(true)
      setToast(null)
      setShowTooltip(false)
      try {
        const resp = await fetch(`${API_BASE}/api/verify/field`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            entity_name: entityName,
            entity_type: entityType || 'company',
            field_name: fieldName,
            claim,
            context: context || null,
            settings,
          }),
        })
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
        const data = await resp.json()
        const newV = { ...data.verification, claim }
        setLocalVerification(newV)
        if (onVerified) onVerified(newV)
        if (data.tavily_used && onTavilyUsed) onTavilyUsed()
      } catch {
        setToast('Verification failed — try again')
        setTimeout(() => setToast(null), 3000)
      } finally {
        setLoadingField(false)
      }
      return
    }
    // Non-pending: cycle human override
    if (!current || current.status === 'pending') return
    const next = current?.human_override === null || !current?.human_override
      ? 'confirmed'
      : current.human_override === 'confirmed'
      ? 'disputed'
      : null
    const updated = { ...current, human_override: next }
    setLocalVerification(updated)
    if (onVerified) onVerified(updated)
  }

  const pendingRingClass = isPending && canVerify
    ? 'ring-1 ring-blue-200 animate-pulse cursor-pointer'
    : isPending
    ? 'border-dashed cursor-not-allowed opacity-50'
    : 'cursor-pointer'

  return (
    <div
      className="relative inline-flex"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <button
        onClick={handleClick}
        disabled={loadingField}
        className={`inline-flex items-center text-[10px] font-bold px-1.5 py-0.5 rounded border transition-opacity hover:opacity-80 select-none ${cfg.color} ${cfg.bg} ${pendingRingClass}`}
      >
        {loadingField
          ? <span className="inline-block w-2.5 h-2.5 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
          : cfg.icon
        }
      </button>

      {toast && (
        <div className="absolute bottom-full left-0 mb-1 z-50 bg-red-600 text-white text-[10px] px-2 py-1 rounded whitespace-nowrap shadow">
          {toast}
        </div>
      )}

      {showTooltip && !loadingField && (
        <Tooltip
          verification={current}
          fieldLabel={fieldLabel || FIELD_LABELS[fieldName]}
          fieldName={fieldName}
          isPending={isPending}
          canVerify={canVerify}
          sessionCapReached={sessionCapReached}
          tavilyEnabled={tavilyEnabled}
        />
      )}
    </div>
  )
}

// Confidence pill
export function ConfidencePill({ confidence, verifications }) {
  const [show, setShow] = useState(false)
  if (!confidence) return null

  const pillCfg = {
    high:   'bg-green-50 text-green-700 border border-green-200',
    medium: 'bg-yellow-50 text-yellow-700 border border-yellow-200',
    low:    'bg-red-50 text-red-600 border border-red-200',
  }[confidence] || 'bg-gray-50 text-gray-500 border border-gray-200'

  const label = { high: 'High confidence', medium: 'Medium confidence', low: 'Low confidence' }[confidence] || confidence

  // Build breakdown rows from verifications dict
  const breakdown = verifications
    ? Object.entries(verifications).map(([field, v]) => {
        const status = v?.status || 'pending'
        const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending
        const fieldLabel = FIELD_LABELS[field] || field
        return { field, fieldLabel, status, cfg, snippet: v?.source_snippet, note: v?.citation_note }
      })
    : []

  const explanation = {
    high:   'All checked fields verified — high confidence in this entry.',
    medium: 'Some fields verified, some unverifiable — treat with reasonable confidence.',
    low:    'One or more contradictions found — review carefully before use.',
  }[confidence] || ''

  return (
    <div className="relative inline-block"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}>
      <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full cursor-default ${pillCfg}`}>
        {label}
      </span>

      {show && (
        <div className="absolute bottom-full right-0 mb-1.5 z-50 w-64 bg-white border border-gray-200 rounded-xl shadow-xl overflow-hidden">
          <div className={`px-3 py-2 border-b border-gray-100 ${
            confidence === 'high' ? 'bg-green-50' :
            confidence === 'low'  ? 'bg-red-50' : 'bg-yellow-50'
          }`}>
            <p className={`text-xs font-semibold ${
              confidence === 'high' ? 'text-green-700' :
              confidence === 'low'  ? 'text-red-600' : 'text-yellow-700'
            }`}>{label}</p>
          </div>
          <div className="px-3 py-2.5 space-y-2">
            <p className="text-[11px] text-gray-500 leading-snug">{explanation}</p>
            {breakdown.length > 0 && (
              <div className="space-y-1 pt-1 border-t border-gray-100">
                {breakdown.map(({ field, fieldLabel, status, cfg, snippet, note }) => (
                  <div key={field} className="flex items-start gap-1.5">
                    <span className={`shrink-0 text-[11px] font-bold mt-0.5 ${cfg.color}`}>{cfg.icon}</span>
                    <div className="min-w-0">
                      <span className="text-[11px] text-gray-700">{fieldLabel}</span>
                      {snippet && (
                        <p className="text-[10px] text-gray-400 italic leading-tight truncate">"{snippet}"</p>
                      )}
                      {note && !snippet && (
                        <p className="text-[10px] text-gray-400 italic leading-tight truncate">{note}</p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
