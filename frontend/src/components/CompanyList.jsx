import React from 'react'
import VerificationBadge, { ConfidencePill } from './VerificationBadge'

const COUNTRY_FLAGS = {
  Germany: '🇩🇪', Austria: '🇦🇹', Switzerland: '🇨🇭',
  France: '🇫🇷', Netherlands: '🇳🇱', Belgium: '🇧🇪',
  Sweden: '🇸🇪', Norway: '🇳🇴', Denmark: '🇩🇰', Finland: '🇫🇮',
  Spain: '🇪🇸', Italy: '🇮🇹', Poland: '🇵🇱', UK: '🇬🇧',
  'United Kingdom': '🇬🇧', Portugal: '🇵🇹', Ireland: '🇮🇪',
  'Czech Republic': '🇨🇿', Romania: '🇷🇴', Hungary: '🇭🇺',
}

const AUTO_REPLACE_FIELDS = new Set(['founded', 'ownership', 'employee_count'])

function fitBadgeClass(score) {
  if (score >= 8) return 'bg-green-100 text-green-800'
  if (score >= 5) return 'bg-yellow-100 text-yellow-700'
  return 'bg-red-100 text-red-600'
}

function normalizeItem(item) {
  if (item && item.company) return item
  return { company: item, verifications: {}, overall_confidence: null }
}

// Returns { displayValue, originalValue, isReplaced }
function resolveValue(original, verification, fieldName) {
  if (!verification) return { displayValue: original, originalValue: original, isReplaced: false }
  const status = verification.status
  const corrected = verification.corrected_value
  const override = verification.human_override
  const canReplace = AUTO_REPLACE_FIELDS.has(fieldName) && corrected

  if (canReplace && status === 'contradicted' && (!override || override === 'confirmed')) {
    return { displayValue: corrected, originalValue: original, isReplaced: true }
  }
  if (canReplace && override === 'disputed') {
    return { displayValue: original, originalValue: original, isReplaced: false }
  }
  return { displayValue: original, originalValue: original, isReplaced: false }
}

// Underline style based on verification status
function underlineClass(verification) {
  if (!verification) return ''
  const eff = verification.human_override || verification.status
  if (eff === 'verified' || eff === 'confirmed') return 'border-b border-green-300'
  if (eff === 'inferred') return 'border-b border-dashed border-gray-300'
  return ''
}

function VerifiedPill({ label, verification, fieldName, badgeProps }) {
  if (!label) return null
  const { displayValue, originalValue, isReplaced } = resolveValue(label, verification, fieldName)
  const uClass = underlineClass(verification)

  return (
    <span className="inline-flex items-center gap-1 bg-gray-100 text-gray-600 text-xs px-2 py-0.5 rounded-full">
      {isReplaced ? (
        <>
          <span className="line-through text-gray-300 text-[10px]">{originalValue}</span>
          <span className={uClass}>{displayValue}</span>
        </>
      ) : (
        <span className={uClass}>{displayValue}</span>
      )}
      {verification && <VerificationBadge verification={verification} fieldName={fieldName} {...badgeProps(fieldName)} />}
    </span>
  )
}

function OwnershipPill({ ownership, verification, badgeProps }) {
  if (!ownership) return null
  const { displayValue, originalValue, isReplaced } = resolveValue(ownership, verification, 'ownership')
  const o = (displayValue || '').toLowerCase()
  let cls = 'bg-gray-100 text-gray-500'
  if (o.startsWith('founder') || o.startsWith('family')) cls = 'bg-emerald-50 text-emerald-700 border border-emerald-200'
  else if (o.startsWith('vc')) cls = 'bg-sky-50 text-sky-700 border border-sky-200'
  else if (o.startsWith('pe-backed')) cls = 'bg-blue-50 text-blue-700 border border-blue-200'
  else if (o.startsWith('public')) cls = 'bg-violet-50 text-violet-700 border border-violet-200'
  else if (o.startsWith('acquired')) cls = 'bg-red-50 text-red-600 border border-red-200'
  const uClass = underlineClass(verification)

  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full ${cls}`}>
      {isReplaced ? (
        <>
          <span className="line-through text-gray-300 text-[10px]">{originalValue}</span>
          <span className={uClass}>{displayValue}</span>
        </>
      ) : (
        <span className={uClass}>{displayValue}</span>
      )}
      {verification && <VerificationBadge verification={verification} fieldName="ownership" {...badgeProps('ownership')} />}
    </span>
  )
}

function CompanyCard({ item, onViewProfile, selected, onToggleSelect, companiesContext, onUpdateVerification, onRemoveCompany, sessionCapReached, onTavilyUsed }) {
  const { company, verifications, overall_confidence } = normalizeItem(item)
  const flag = COUNTRY_FLAGS[company.country] || '🌍'
  const location = [company.hq_city, company.country].filter(Boolean).join(', ')

  const existenceV = verifications.existence
  const existenceContradicted = existenceV?.status === 'contradicted'

  const badgeProps = (fieldName) => ({
    entityName: company.name,
    entityType: 'company',
    fieldName,
    context: companiesContext,
    onVerified: (v) => onUpdateVerification?.(company.name, fieldName, v),
    onTavilyUsed,
    sessionCapReached,
  })

  return (
    <div className={`bg-white border rounded-xl p-5 shadow-sm space-y-3 transition-colors ${selected ? 'border-blue-400 ring-1 ring-blue-200' : 'border-gray-200'}`}>
      {/* Existence warning */}
      {existenceContradicted && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 flex items-center justify-between gap-2">
          <p className="text-xs text-red-700 font-medium">⚠ Could not verify this company exists — treat with caution</p>
          {onRemoveCompany && (
            <button onClick={() => onRemoveCompany(company.name)}
              className="text-xs text-red-600 hover:text-red-800 border border-red-300 px-2 py-0.5 rounded shrink-0">
              Remove
            </button>
          )}
        </div>
      )}

      <div className="flex justify-between items-start">
        <div className="flex items-start gap-2">
          <input type="checkbox" checked={selected} onChange={onToggleSelect}
            className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600 cursor-pointer shrink-0"
            onClick={e => e.stopPropagation()} />
          <div>
            <h3 className="font-semibold text-gray-900">{flag} {company.name}</h3>
            <p className="text-xs text-gray-500 mt-0.5">{location}</p>
          </div>
        </div>
        <div className="flex flex-col items-end gap-1.5">
          <span className={`text-sm font-bold px-3 py-1 rounded-full ${fitBadgeClass(company.fit_score)}`}>
            {company.fit_score}/10
          </span>
          <ConfidencePill confidence={overall_confidence} verifications={verifications} />
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5 items-center">
        <OwnershipPill ownership={company.ownership} verification={verifications.ownership} badgeProps={badgeProps} />
        {company.founded && (
          <VerifiedPill label={`Founded ${company.founded}`} verification={verifications.founded} fieldName="founded" badgeProps={badgeProps} />
        )}
        {company.estimated_arr && (
          <VerifiedPill label={`ARR ${company.estimated_arr}`} verification={verifications.estimated_arr} fieldName="estimated_arr" badgeProps={badgeProps} />
        )}
        {company.employee_count && (
          <VerifiedPill label={`${company.employee_count} employees`} verification={verifications.employee_count} fieldName="employee_count" badgeProps={badgeProps} />
        )}
      </div>

      {/* Website warnings */}
      {verifications.website?.status === 'contradicted' && (
        <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-600">
          ⚠ Website unreachable — {verifications.website.citation_note || 'may be broken or company no longer exists'}
        </div>
      )}
      {verifications.website?.status === 'inferred' && verifications.website?.citation_note?.includes('rebrand') && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-700">
          ↪ {verifications.website.source_snippet}
          {verifications.website.source_url && (
            <a href={verifications.website.source_url} target="_blank" rel="noopener noreferrer" className="ml-1 underline">
              {verifications.website.source_url}
            </a>
          )}
        </div>
      )}

      <p className="text-sm text-gray-600 leading-relaxed">{company.description}</p>
      <p className="text-xs text-gray-500 italic">{company.fit_rationale}</p>

      {company.signals?.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {company.signals.map((s, i) => (
            <span key={i} className="bg-purple-50 text-purple-700 text-xs px-2 py-0.5 rounded-full">{s}</span>
          ))}
        </div>
      )}

      <div className="flex gap-2 pt-1">
        {company.website && (
          <a href={company.website} target="_blank" rel="noopener noreferrer"
            className="text-xs bg-gray-100 hover:bg-gray-200 text-gray-700 px-3 py-1.5 rounded-lg transition-colors">
            Website ↗
          </a>
        )}
        <button onClick={() => onViewProfile(company)}
          className="text-xs bg-blue-600 hover:bg-blue-700 text-white px-3 py-1.5 rounded-lg transition-colors">
          View Full Profile
        </button>
      </div>
    </div>
  )
}

export default function CompanyList({
  companies, onViewProfile, selectedCompanies = [], onToggleCompany,
  companiesContext = "", onUpdateVerification, sessionCapReached, onTavilyUsed,
}) {
  const [removed, setRemoved] = React.useState(new Set())

  if (!companies?.length) {
    return (
      <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-sm text-amber-700">
        No company data returned. Try refining your thesis or check your API keys.
      </div>
    )
  }

  const visible = companies.filter(item => {
    const c = item?.company || item
    return !removed.has(c.name)
  })

  return (
    <div>
      <h2 className="text-lg font-bold text-gray-800 mb-4">
        Company Universe{' '}
        <span className="text-sm font-normal text-gray-400">
          ({visible.length} companies{removed.size > 0 ? `, ${removed.size} removed` : ''})
        </span>
      </h2>
      <div className="space-y-4">
        {visible.map((item, i) => {
          const company = item?.company || item
          return (
            <CompanyCard
              key={i}
              item={item}
              onViewProfile={onViewProfile}
              selected={selectedCompanies.some(s => s.name === company.name)}
              onToggleSelect={() => onToggleCompany?.(company)}
              companiesContext={companiesContext}
              onUpdateVerification={onUpdateVerification}
              onRemoveCompany={(name) => setRemoved(prev => new Set([...prev, name]))}
              sessionCapReached={sessionCapReached}
              onTavilyUsed={onTavilyUsed}
            />
          )
        })}
      </div>
    </div>
  )
}
