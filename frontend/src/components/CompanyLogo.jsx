import React, { useState } from 'react'

function domainFromUrl(url) {
  if (!url) return null
  try {
    const m = url.match(/https?:\/\/(?:www\.)?([^/]+)/)
    return m ? m[1] : null
  } catch { return null }
}

function initialsColor(name) {
  const colors = [
    'bg-blue-600', 'bg-violet-600', 'bg-emerald-600',
    'bg-amber-600', 'bg-rose-600', 'bg-cyan-600', 'bg-indigo-600',
  ]
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return colors[Math.abs(hash) % colors.length]
}

/**
 * Company logo with a three-level fallback:
 * 1. Clearbit (high-quality logo for known brands)
 * 2. Google favicon service (works for any site with a favicon)
 * 3. Initials avatar (always renders)
 */
export default function CompanyLogo({ website, name, size = 'md' }) {
  const domain = domainFromUrl(website)
  const clearbitUrl = domain ? `https://logo.clearbit.com/${domain}` : null
  const faviconUrl = domain ? `https://www.google.com/s2/favicons?sz=64&domain=${domain}` : null

  const [src, setSrc] = useState(clearbitUrl)
  const [failed, setFailed] = useState(false)

  const sizeClasses = {
    sm: 'h-6 w-6 text-[10px]',
    md: 'h-8 w-8 text-xs',
    lg: 'h-10 w-10 text-sm',
  }
  const imgSizeClasses = {
    sm: 'h-6 w-6',
    md: 'h-8 w-8',
    lg: 'h-10 w-10',
  }

  const initials = (name || '?')
    .split(/[\s\-&]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(w => w[0].toUpperCase())
    .join('')

  const handleError = () => {
    if (src === clearbitUrl && faviconUrl) {
      setSrc(faviconUrl)
    } else {
      setFailed(true)
    }
  }

  if (!domain || failed) {
    return (
      <div className={`${sizeClasses[size]} ${initialsColor(name || '')} rounded flex items-center justify-center font-bold text-white shrink-0`}>
        {initials}
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={`${name} logo`}
      className={`${imgSizeClasses[size]} object-contain rounded bg-white shrink-0`}
      onError={handleError}
    />
  )
}
