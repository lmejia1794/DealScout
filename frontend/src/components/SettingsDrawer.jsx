import React, { useState } from 'react'
import { useSettings } from './SettingsContext'
import { DEFAULTS, OPENROUTER_MODELS, GOOGLE_MODELS } from './settingsDefaults'

function Field({ label, hint, children }) {
  return (
    <div className="space-y-1">
      <label className="block text-xs font-semibold text-gray-700">{label}</label>
      {hint && <p className="text-xs text-gray-400">{hint}</p>}
      {children}
    </div>
  )
}

export default function SettingsDrawer() {
  const { settings, update, reset } = useSettings()
  const [open, setOpen] = useState(false)
  const [showAdvanced, setShowAdvanced] = useState(false)

  return (
    <>
      {/* Gear button */}
      <button
        onClick={() => setOpen(true)}
        title="Settings"
        className="text-gray-400 hover:text-gray-600 transition-colors p-1 rounded-lg hover:bg-gray-100"
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 0 1 0 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28Z" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
        </svg>
      </button>

      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 bg-black/30 z-40"
          onClick={() => setOpen(false)}
        />
      )}

      {/* Drawer */}
      <div
        className={`
          fixed top-0 right-0 h-full w-full max-w-sm bg-white shadow-2xl z-50
          transform transition-transform duration-300
          ${open ? 'translate-x-0' : 'translate-x-full'}
          flex flex-col
        `}
      >
        <div className="flex justify-between items-center px-5 py-4 border-b border-gray-200">
          <h2 className="font-semibold text-gray-900">Settings</h2>
          <button
            onClick={() => setOpen(false)}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-5 space-y-5">

          {/* Tavily max results */}
          <Field label="Tavily max results" hint="Results per search query (1–10).">
            <input
              type="number" min={1} max={10}
              value={settings.tavily_max_results}
              onChange={e => update('tavily_max_results', parseInt(e.target.value, 10))}
              className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-400"
            />
          </Field>

          {/* Search provider */}
          <Field
            label="Search provider"
            hint={settings.search_provider === 'tavily' ? 'Higher quality, uses Tavily credits.' : 'Free, no API key required. May be rate-limited.'}
          >
            <div className="flex rounded-lg border border-gray-200 overflow-hidden text-sm">
              {[['tavily', 'Tavily'], ['duckduckgo', 'DuckDuckGo']].map(([val, label]) => (
                <button
                  key={val}
                  onClick={() => update('search_provider', val)}
                  className={`flex-1 py-1.5 transition-colors ${
                    settings.search_provider === val
                      ? 'bg-blue-600 text-white font-medium'
                      : 'text-gray-600 hover:bg-gray-50'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </Field>

          {/* Google AI Studio */}
          <Field label="Google AI model" hint="Primary LLM — free at aistudio.google.com. Automatically falls back to 2.0 Flash if unavailable.">
            <select
              value={settings.google_model}
              onChange={e => update('google_model', e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white"
            >
              {GOOGLE_MODELS.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </Field>

          <Field label="Google Search grounding" hint="Adds live web results on top of pre-injected search context.">
            <label className="flex items-center gap-2 cursor-pointer mt-1">
              <div
                onClick={() => update('google_use_search', !settings.google_use_search)}
                className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
                  settings.google_use_search ? 'bg-blue-600' : 'bg-gray-200'
                }`}
              >
                <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  settings.google_use_search ? 'translate-x-4' : 'translate-x-0'
                }`} />
              </div>
              <span className="text-sm text-gray-700">
                {settings.google_use_search ? 'Enabled' : 'Disabled'}
              </span>
            </label>
          </Field>

          {/* OpenRouter fallback */}
          <Field label="OpenRouter fallback" hint="Used when GOOGLE_API_KEY is not set. Free tier only.">
            <select
              value={settings.openrouter_model}
              onChange={e => update('openrouter_model', e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white"
            >
              {OPENROUTER_MODELS.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </Field>

          {/* Contact enrichment */}
          <Field
            label="Contact enrichment"
            hint="Attempts to find email and phone for each decision maker. Adds ~15s per person."
          >
            <label className="flex items-center gap-2 cursor-pointer mt-1">
              <div
                onClick={() => update('contact_enrichment_enabled', !settings.contact_enrichment_enabled)}
                className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
                  settings.contact_enrichment_enabled ? 'bg-blue-600' : 'bg-gray-200'
                }`}
              >
                <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  settings.contact_enrichment_enabled ? 'translate-x-4' : 'translate-x-0'
                }`} />
              </div>
              <span className="text-sm text-gray-700">
                {settings.contact_enrichment_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </label>
          </Field>

          {/* Source scraping */}
          <Field
            label="AI source scraping"
            hint="Gemini picks authoritative sites to scrape for richer context. Adds ~10s to research time."
          >
            <label className="flex items-center gap-2 cursor-pointer mt-1">
              <div
                onClick={() => update('source_scraping_enabled', !settings.source_scraping_enabled)}
                className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
                  settings.source_scraping_enabled ? 'bg-blue-600' : 'bg-gray-200'
                }`}
              >
                <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  settings.source_scraping_enabled ? 'translate-x-4' : 'translate-x-0'
                }`} />
              </div>
              <span className="text-sm text-gray-700">
                {settings.source_scraping_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </label>
          </Field>

          {/* Registry lookup */}
          <Field
            label="Registry lookup"
            hint="Overwrites LLM-inferred founding year and legal name with authoritative registry data (Companies House, Wikidata). Free."
          >
            <label className="flex items-center gap-2 cursor-pointer mt-1">
              <div
                onClick={() => update('registry_enrichment_enabled', !settings.registry_enrichment_enabled)}
                className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
                  settings.registry_enrichment_enabled ? 'bg-blue-600' : 'bg-gray-200'
                }`}
              >
                <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  settings.registry_enrichment_enabled ? 'translate-x-4' : 'translate-x-0'
                }`} />
              </div>
              <span className="text-sm text-gray-700">
                {settings.registry_enrichment_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </label>
          </Field>

          {/* Recent news */}
          <Field
            label="Recent news"
            hint="NewsAPI: PE-relevant articles only. 100 req/day free, cached per session."
          >
            <label className="flex items-center gap-2 cursor-pointer mt-1">
              <div
                onClick={() => update('news_enrichment_enabled', !settings.news_enrichment_enabled)}
                className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
                  settings.news_enrichment_enabled ? 'bg-blue-600' : 'bg-gray-200'
                }`}
              >
                <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  settings.news_enrichment_enabled ? 'translate-x-4' : 'translate-x-0'
                }`} />
              </div>
              <span className="text-sm text-gray-700">
                {settings.news_enrichment_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </label>
          </Field>

          {/* PDL contact lookup */}
          <Field
            label="PDL contact lookup"
            hint="LinkedIn URLs only on free tier (100 lookups/month). Requires PDL_API_KEY."
          >
            <label className="flex items-center gap-2 cursor-pointer mt-1">
              <div
                onClick={() => update('pdl_enrichment_enabled', !settings.pdl_enrichment_enabled)}
                className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
                  settings.pdl_enrichment_enabled ? 'bg-blue-600' : 'bg-gray-200'
                }`}
              >
                <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  settings.pdl_enrichment_enabled ? 'translate-x-4' : 'translate-x-0'
                }`} />
              </div>
              <span className="text-sm text-gray-700">
                {settings.pdl_enrichment_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </label>
          </Field>

          {/* AI verification */}
          <Field
            label="AI verification pass"
            hint="Fact-checks generated content after each research run. Adds ~2 minutes."
          >
            <label className="flex items-center gap-2 cursor-pointer mt-1">
              <div
                onClick={() => update('verification_enabled', !settings.verification_enabled)}
                className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
                  settings.verification_enabled ? 'bg-blue-600' : 'bg-gray-200'
                }`}
              >
                <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                  settings.verification_enabled ? 'translate-x-4' : 'translate-x-0'
                }`} />
              </div>
              <span className="text-sm text-gray-700">
                {settings.verification_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </label>
          </Field>

          {settings.verification_enabled && (
            <div className="ml-4 space-y-3 border-l-2 border-gray-100 pl-4">
              <Field
                label="Tavily re-verification"
                hint="Uses Tavily credits to corroborate claims. Adds ~2 min."
              >
                <label className="flex items-center gap-2 cursor-pointer mt-1">
                  <div
                    onClick={() => update('verification_tavily_enabled', !settings.verification_tavily_enabled)}
                    className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
                      settings.verification_tavily_enabled ? 'bg-blue-600' : 'bg-gray-200'
                    }`}
                  >
                    <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                      settings.verification_tavily_enabled ? 'translate-x-4' : 'translate-x-0'
                    }`} />
                  </div>
                  <span className="text-sm text-gray-700">
                    {settings.verification_tavily_enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </label>
              </Field>

              <Field
                label="Citation extraction"
                hint="Asks Gemini to cite sources inline at generation time. Free."
              >
                <label className="flex items-center gap-2 cursor-pointer mt-1">
                  <div
                    onClick={() => update('verification_citations_enabled', !settings.verification_citations_enabled)}
                    className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${
                      settings.verification_citations_enabled ? 'bg-blue-600' : 'bg-gray-200'
                    }`}
                  >
                    <div className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${
                      settings.verification_citations_enabled ? 'translate-x-4' : 'translate-x-0'
                    }`} />
                  </div>
                  <span className="text-sm text-gray-700">
                    {settings.verification_citations_enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </label>
              </Field>
            </div>
          )}

          {/* Advanced settings */}
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              onClick={() => setShowAdvanced(v => !v)}
              className="w-full flex items-center justify-between px-3 py-2.5 text-xs font-semibold text-gray-600 hover:bg-gray-50 transition-colors"
            >
              <span>Advanced</span>
              <svg
                className={`w-3.5 h-3.5 text-gray-400 transition-transform ${showAdvanced ? 'rotate-180' : ''}`}
                fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {showAdvanced && (
              <div className="px-3 pb-4 pt-2 space-y-4 border-t border-gray-100">
                {/* Temperature */}
                <Field label="Temperature" hint="Lower = more deterministic. Higher = more creative.">
                  <div className="flex items-center gap-3">
                    <input
                      type="range" min={0} max={1} step={0.05}
                      value={settings.temperature}
                      onChange={e => update('temperature', parseFloat(e.target.value))}
                      className="flex-1"
                    />
                    <span className="text-xs font-mono w-8 text-right text-gray-700">
                      {settings.temperature.toFixed(2)}
                    </span>
                  </div>
                </Field>

                {/* Token limits */}
                <div className="grid grid-cols-2 gap-3">
                  {[
                    ['max_tokens_brief',    'Max tokens — brief'],
                    ['max_tokens_json',     'Max tokens — JSON'],
                    ['max_tokens_profile',  'Max tokens — profile'],
                    ['max_tokens_outreach', 'Max tokens — outreach'],
                  ].map(([key, label]) => (
                    <Field key={key} label={label}>
                      <input
                        type="number" min={100} max={8000} step={100}
                        value={settings[key]}
                        onChange={e => update(key, parseInt(e.target.value, 10))}
                        className="w-full border border-gray-200 rounded-lg px-2.5 py-1.5 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-blue-400"
                      />
                    </Field>
                  ))}
                </div>

                {/* System prompt */}
                <Field label="System prompt">
                  <textarea
                    rows={5}
                    value={settings.system_prompt}
                    onChange={e => update('system_prompt', e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-2.5 py-2 text-sm text-gray-800 font-mono resize-y focus:outline-none focus:ring-2 focus:ring-blue-400"
                  />
                </Field>
              </div>
            )}
          </div>
        </div>

        <div className="px-5 py-4 border-t border-gray-200">
          <button
            onClick={() => { reset(); setOpen(false) }}
            className="w-full text-sm text-red-500 hover:text-red-700 border border-red-200 hover:border-red-400 py-2 rounded-lg transition-colors"
          >
            Reset to defaults
          </button>
        </div>
      </div>
    </>
  )
}
