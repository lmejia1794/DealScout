import React, { createContext, useContext, useState, useEffect } from 'react'
import { DEFAULTS, OPENROUTER_MODELS, GOOGLE_MODELS } from './settingsDefaults'

const STORAGE_KEY = 'dealscout_settings'

const SettingsContext = createContext(null)

export function SettingsProvider({ children }) {
  const [settings, setSettings] = useState(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
      const merged = { ...DEFAULTS, ...stored }
      // Reset models to defaults if stored values are no longer valid options
      if (merged.openrouter_model && !OPENROUTER_MODELS.includes(merged.openrouter_model)) {
        merged.openrouter_model = DEFAULTS.openrouter_model
      }
      if (merged.google_model && !GOOGLE_MODELS.includes(merged.google_model)) {
        merged.google_model = DEFAULTS.google_model
      }
      return merged
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
