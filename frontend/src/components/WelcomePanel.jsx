import React from 'react'

export const EXAMPLES = [
  {
    label: 'Workforce management / DACH & Nordics',
    thesis: 'European workforce management software for SMBs in DACH and Nordics, ARR €8–30M, founder-led or PE secondary, EV €80–250M',
  },
  {
    label: 'Fleet telematics & route optimisation / Western Europe',
    thesis: 'B2B fleet telematics and route optimisation SaaS, HQ in Western Europe, targeting logistics and field-service companies, ARR €5–25M',
  },
  {
    label: 'eInvoicing & AP automation / Southern Europe & Benelux',
    thesis: 'eInvoicing and AP automation software for mid-market manufacturers in Southern Europe and Benelux, €10–40M ARR, not yet acquired by a strategic',
  },
  {
    label: 'Clinical trial management / European CROs & biotech',
    thesis: 'Clinical trial management and eTMF software for European CROs and biotech, founder-led, €5–20M ARR, potential PE secondary',
  },
  {
    label: 'EHS compliance SaaS / Germany & Benelux industrials',
    thesis: 'EHS (environment, health & safety) compliance SaaS for industrial companies in Germany and Benelux, recurring revenue >70%, €8–30M ARR',
  },
]

const STEPS = [
  {
    number: '1',
    title: 'Write your thesis',
    desc: 'Describe the sector, geography, and deal criteria — include ARR range, EV window, and ownership type for sharper results.',
  },
  {
    number: '2',
    title: 'Research runs automatically',
    desc: 'DealScout builds a sector brief, surfaces upcoming conferences, and curates a ranked acquisition target list from live web data.',
  },
  {
    number: '3',
    title: 'Review and act',
    desc: 'Enrich company profiles, pull comparable transactions, and export a one-page investment committee brief.',
  },
]

export default function WelcomePanel({ onSelectExample, onRunExample }) {
  return (
    <div className="mt-10 space-y-10">
      {/* Value prop */}
      <div className="text-center">
        <h2 className="text-2xl font-bold text-gray-800">Your PE deal sourcing copilot</h2>
        <p className="mt-2 text-sm text-gray-500 max-w-xl mx-auto">
          Describe a sector and deal criteria, and DealScout returns a sector brief, relevant conferences,
          and a curated company universe — sourced from live web data and verified inline, in under two minutes.
        </p>
      </div>

      {/* How it works */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {STEPS.map((step) => (
          <div key={step.number} className="bg-white border border-gray-200 rounded-xl p-5">
            <div className="w-7 h-7 rounded-full bg-blue-600 text-white text-xs font-bold flex items-center justify-center mb-3">
              {step.number}
            </div>
            <p className="text-sm font-semibold text-gray-800">{step.title}</p>
            <p className="text-xs text-gray-500 mt-1 leading-relaxed">{step.desc}</p>
          </div>
        ))}
      </div>

      {/* Example theses */}
      <div>
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Example theses</p>
        <div className="space-y-2">
          {EXAMPLES.map((ex) => (
            <div
              key={ex.thesis}
              className="bg-white border border-gray-200 rounded-lg px-4 py-3 flex items-center gap-3 group hover:border-blue-300 transition-colors"
            >
              <button
                onClick={() => onSelectExample(ex.thesis)}
                className="flex-1 min-w-0 text-left"
              >
                <p className="text-xs font-medium text-blue-600">{ex.label}</p>
                <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">{ex.thesis}</p>
              </button>
              <button
                onClick={() => onRunExample(ex.thesis)}
                className="shrink-0 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-3 py-1.5 rounded-md transition-colors whitespace-nowrap"
              >
                Run Research →
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
