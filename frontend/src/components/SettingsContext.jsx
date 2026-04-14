import React, { createContext, useContext, useState, useEffect } from 'react'

const STORAGE_KEY = 'dealscout_settings'

export const DEFAULTS = {
  temperature: 0.2,
  max_tokens_brief: 1500,
  max_tokens_json: 2000,
  max_tokens_profile: 2500,
  max_tokens_outreach: 500,
  system_prompt:
    'You are a structured data assistant. When asked to return JSON, return ONLY valid JSON with no markdown fences, no preamble, and no explanation. When asked to return markdown, return only markdown.',
  tavily_max_results: 5,
  ollama_model: 'mixtral:8x7b-instruct-v0.1-q4_K_M',
  source_scraping_enabled: true,
  contact_enrichment_enabled: true,
  verification_enabled: true,
  verification_tavily_enabled: true,
  verification_citations_enabled: true,
  verification_tavily_max_calls: 20,
}

const SettingsContext = createContext(null)

export function SettingsProvider({ children }) {
  const [settings, setSettings] = useState(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
      return { ...DEFAULTS, ...stored }
    } catch {
      return { ...DEFAULTS }
    }
  })

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings))
  }, [settings])

  const update = (key, value) =>
    setSettings(prev => ({ ...prev, [key]: value }))

  const reset = () => {
    setSettings({ ...DEFAULTS })
    localStorage.removeItem(STORAGE_KEY)
  }

  return (
    <SettingsContext.Provider value={{ settings, update, reset }}>
      {children}
    </SettingsContext.Provider>
  )
}

export function useSettings() {
  return useContext(SettingsContext)
}
