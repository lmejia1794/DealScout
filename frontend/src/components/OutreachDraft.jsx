import React, { useState } from 'react'
import { API_BASE } from '../config'

export default function OutreachDraft({ company, profile, thesis }) {
  const [state, setstate] = useState('idle') // idle | loading | done | error
  const [subject, setSubject] = useState('')
  const [body, setBody] = useState('')
  const [copied, setCopied] = useState(false)

  async function draft() {
    setstate('loading')
    try {
      const resp = await fetch(`${API_BASE}/api/company/outreach`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ company, profile, thesis }),
      })
      const data = await resp.json()
      setSubject(data.subject || '')
      setBody(data.body || '')
      setstate('done')
    } catch (e) {
      setstate('error')
    }
  }

  function copyToClipboard() {
    const text = `Subject: ${subject}\n\n${body}`
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  if (state === 'idle') {
    return (
      <button
        onClick={draft}
        className="w-full py-2.5 text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
      >
        Draft Outreach Email
      </button>
    )
  }

  if (state === 'loading') {
    return (
      <div className="flex items-center justify-center gap-3 py-4 text-sm text-gray-500">
        <span className="w-4 h-4 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
        Drafting email...
      </div>
    )
  }

  if (state === 'error') {
    return (
      <div className="text-sm text-red-500 py-2">
        Failed to draft email.{' '}
        <button onClick={draft} className="underline">Retry</button>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1">Subject</label>
        <input
          type="text"
          value={subject}
          onChange={e => setSubject(e.target.value)}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-gray-600 mb-1">Body</label>
        <textarea
          rows={8}
          value={body}
          onChange={e => setBody(e.target.value)}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-800 resize-y focus:outline-none focus:ring-2 focus:ring-blue-400"
        />
      </div>
      <div className="flex items-center justify-between">
        <button
          onClick={copyToClipboard}
          className="text-sm bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg transition-colors"
        >
          {copied ? '✓ Copied' : 'Copy to Clipboard'}
        </button>
        <button
          onClick={draft}
          className="text-xs text-gray-400 hover:text-gray-600 underline"
        >
          Regenerate
        </button>
      </div>
      <p className="text-xs text-gray-400 italic">
        AI-generated draft — review before sending
      </p>
    </div>
  )
}
