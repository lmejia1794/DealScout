# DealScout

**AI-powered deal sourcing copilot for European B2B software investors.**

DealScout takes a plain-English investment thesis and returns a structured sector brief, upcoming relevant conferences, and a ranked list of acquisition targets — all in under two minutes, sourced from live web data and verified inline.

**Live demo:** [dealscout-1.onrender.com](https://dealscout-1.onrender.com/)

---

## What it does

| Output | Description |
|---|---|
| **Sector Brief** | 11-section IC-ready memo covering market definition, size & growth, demand drivers, sub-sector breakdown, competitive landscape, M&A activity, ideal target profile, value creation levers, exit landscape, red flags, and key management questions |
| **Conference List** | 5–8 upcoming European sector events with dates, cost estimates, and notable attendees |
| **Company Universe** | 8–12 ranked acquisition targets with fit scores, ownership status, ARR estimates, and growth signals |
| **Company Profiles** | Deep-dive on any target: financials, decision-makers, verified facts, outreach email draft |
| **Comparable Transactions** | Recent M&A comps with EV/ARR and EV/EBITDA multiples |

Every factual claim is sourced inline with a numbered citation. Citations are verified post-generation and flagged if hallucinated.

---

## Example prompts

```
European workforce management software for SMBs in DACH and Nordics,
ARR €8–30M, founder-led or PE secondary, EV €80–250M
```

```
B2B fleet telematics and route optimisation SaaS, HQ in Western Europe,
targeting logistics and field-service companies, ARR €5–25M
```

```
eInvoicing and AP automation software for mid-market manufacturers in
Southern Europe and Benelux, €10–40M ARR, not yet acquired by a strategic
```

```
Clinical trial management and eTMF software for European CROs and biotech,
founder-led, €5–20M ARR, potential PE secondary
```

```
EHS (environment, health & safety) compliance SaaS for industrial companies
in Germany and Benelux, recurring revenue >70%, €8–30M ARR
```

The more specific the thesis — geography, size window, ownership type — the sharper the output.

---

## How it works

```
Investment thesis
      │
      ▼
┌─────────────────────────────────────────────────┐
│  Step 1 — Sector Brief                          │
│  Gemini 2.5 Flash + Google Search grounding     │
│  → 9-section IC memo with inline citations      │
└─────────────────────────────────────────────────┘
      │  (runs concurrently ↓)
      ├──────────────────────────────────────────────┐
      ▼                                              ▼
┌─────────────────────┐              ┌──────────────────────────┐
│  Step 2 — Conferences│              │  Citation Repair Thread  │
│  JSON via Gemini    │              │  HEAD-checks all URLs,   │
│  → 5–8 upcoming     │              │  follows Gemini redirect  │
│    sector events    │              │  tokens, replaces broken  │
└─────────────────────┘              │  links via site: search  │
      │                              └──────────────────────────┘
      ▼
┌─────────────────────┐
│  Step 3 — Companies │
│  JSON via Gemini    │
│  → 8–12 ranked      │
│    targets          │
└─────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────┐
│  Verification Pass                              │
│  Secondary LLM cross-checks key fields          │
│  against live Tavily search results             │
└─────────────────────────────────────────────────┘
```

**LLM routing** (priority order):
1. Google AI Studio — Gemini 2.5 Flash with native Search grounding (free)
2. Groq — Llama 3.3 70B (free tier, fast)
3. OpenRouter — Llama 3.3 70B free tier (slower fallback)

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS |
| Backend | Python 3.11, FastAPI, Uvicorn |
| Primary LLM | Google Gemini 2.5 Flash via `google-genai` |
| Fallback LLMs | Groq API, OpenRouter |
| Search / grounding | Tavily API, DuckDuckGo (free fallback) |
| Verification | Tavily + secondary LLM cross-check |
| Enrichment | Companies House, Wikidata, NewsAPI, PDL, Hunter.io, Clearbit Logo |
| Deployment | Render (backend + frontend) |

---

## Local setup

### Prerequisites

- Python 3.10+
- Node 18+
- At minimum one LLM API key (Google AI Studio is free at [aistudio.google.com](https://aistudio.google.com))

### 1. Clone and install

```bash
git clone https://github.com/your-org/dealscout.git
cd dealscout

# Backend
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### 2. Configure environment variables

Copy the example and fill in your keys:

```bash
cp .env.example .env
```

```env
# LLM providers (priority: Google → Groq → OpenRouter)
GOOGLE_API_KEY=          # free: aistudio.google.com
GOOGLE_MODEL=gemini-2.5-flash
GOOGLE_USE_SEARCH=true
GROQ_API_KEY=            # free: console.groq.com
GROQ_MODEL=llama-3.3-70b-versatile
OPENROUTER_API_KEY=      # free tier: openrouter.ai
OPENROUTER_MODEL=meta-llama/llama-3.3-70b-instruct:free

# Search (Tavily recommended — free tier available at tavily.com)
TAVILY_API_KEY=
WEB_CTX_MAX=4000

# Verification
VERIFICATION_TAVILY_ENABLED=true
VERIFICATION_CITATIONS_ENABLED=true
VERIFICATION_TAVILY_MAX_CALLS=20
CITATION_FETCH_MAX_CHARS=3000

```

Only `GOOGLE_API_KEY` (or one of the fallback LLM keys) is required to run. Tavily is strongly recommended for citation quality but DuckDuckGo will be used automatically if `TAVILY_API_KEY` is not set.

**Enrichment API keys** (all optional, all free tiers available):

| Key | Source | What it adds |
|---|---|---|
| `COMPANIES_HOUSE_API_KEY` | [developer.company-information.service.gov.uk](https://developer.company-information.service.gov.uk) | Authoritative founding date, legal name, status for UK companies |
| `NEWS_API_KEY` | [newsapi.org](https://newsapi.org) | PE-relevant recent news on company cards (100 req/day free) |
| `PDL_API_KEY` | [peopledatalabs.com](https://peopledatalabs.com) | LinkedIn URLs for decision makers (100 lookups/month free) |
| `HUNTER_API_KEY` | [hunter.io](https://hunter.io) | Professional email addresses for decision makers |

Wikidata (founding year, country, website) and Clearbit Logo are free with no key required.

### 3. Run

```bash
# Terminal 1 — backend
cd backend
source .venv/bin/activate
uvicorn main:app --reload
# API available at http://localhost:8000
# API docs at http://localhost:8000/docs

# Terminal 2 — frontend
cd frontend
npm run dev
# App available at http://localhost:5173
```

---

## Project structure

```
dealscout/
├── backend/
│   ├── main.py          # FastAPI app, SSE streaming endpoints
│   ├── research.py      # Pipeline: sector brief → conferences → companies
│   ├── verification.py  # Post-generation fact-checking and citation repair
│   ├── profile.py       # Phase 2: company deep-dive profiles
│   ├── comparables.py   # Phase 3: M&A comparable transactions
│   ├── search.py        # Tavily / DuckDuckGo search utilities
│   ├── registries.py    # Companies House, Wikidata, NewsAPI, Clearbit Logo
│   ├── enrichment.py    # Contact enrichment (Hunter.io, PDL)
│   ├── scraper.py       # Source page scraping for grounding context
│   ├── models.py        # Pydantic request/response models
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.jsx               # Main state, search, saved searches
│       └── components/
│           ├── SearchBar.jsx
│           ├── SectorBrief.jsx      # Markdown renderer with citation footnotes
│           ├── CompanyList.jsx
│           ├── CompanyModal.jsx     # Deep-dive profile panel
│           ├── ConferenceGrid.jsx
│           ├── ComparablesPanel.jsx
│           ├── DecisionMakers.jsx
│           ├── OutreachDraft.jsx
│           ├── ReportView.jsx
│           ├── ReportActionBar.jsx
│           ├── ServiceMap.jsx
│           ├── LlmBadge.jsx         # LLM attribution badge
│           ├── VerificationBadge.jsx
│           ├── PipelineContext.jsx  # Multi-job state management
│           ├── SettingsContext.jsx
│           └── SavedSearches.jsx
├── .env.example
└── README.md
```

---

## API reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/research` | POST | Full pipeline — streams SSE log + phase results |
| `/api/research/step` | POST | Regenerate one step (`sector_brief`, `conferences`, or `companies`) with current context |
| `/api/company/profile` | POST | Deep-dive profile for a single company |
| `/api/company/outreach` | POST | Generate personalised outreach email |
| `/api/comparables` | POST | Pull comparable M&A transactions |
| `/api/verify/field` | POST | On-demand field verification |
| `/health` | GET | Health check |

All research endpoints return [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events) so the UI can stream live pipeline logs and phase results incrementally.

---

## Settings

The frontend exposes a settings drawer (gear icon) with controls for:

- **LLM model** — override the default Gemini model
- **Search provider** — Tavily or DuckDuckGo
- **Google Search grounding** — toggle native web search on/off
- **Verification** — enable/disable post-generation fact-checking
- **Registry lookup** — Companies House + Wikidata overrides for founding year, legal name, status (free)
- **Recent news** — NewsAPI PE-relevant articles on company profiles (100 req/day free)
- **PDL contact lookup** — LinkedIn URLs for decision makers (100 lookups/month free)
- **Citation verification** — enable/disable inline citation repair
- **Contact enrichment** — enable/disable decision-maker email/phone lookup
- **Source scraping** — enable/disable source page pre-fetching

---

## Roadmap

- [x] Phase 1 — Sector brief, conference list, company universe
- [x] Phase 2 — Company deep-dive profiles, decision-maker identification, outreach drafts
- [x] Phase 3 — Comparable M&A transactions panel
- [ ] CRM tracker — pipeline stage tracking across saved searches
- [ ] PDF / Word export — IC-ready one-pager per company
- [ ] Webhook / scheduled refresh — re-run saved searches on a cadence
