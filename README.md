# DealScout

**AI-powered deal sourcing copilot for European B2B software investors.**

DealScout takes a plain-English investment thesis and returns a structured sector brief, upcoming relevant conferences, and a ranked list of acquisition targets — all in under two minutes, sourced from live web data and verified inline.

**Live demo:** [dealscout-1.onrender.com](https://dealscout-1.onrender.com/)

---

## What it does

| Output | Description |
|---|---|
| **Sector Brief** | 11-section IC-ready memo: market definition, size & growth, demand drivers, sub-sector breakdown, competitive landscape, M&A activity, ideal target profile, value creation levers, exit landscape, red flags, and key management questions |
| **Conference List** | 5–8 upcoming European sector events with dates, cost estimates, and notable attendees |
| **Company Universe** | 8–12 ranked acquisition targets with fit scores, ownership status, ARR estimates, and growth signals |
| **Company Profiles** | Deep-dive on any target: financials, decision-makers, verified facts, outreach email draft |
| **Comparable Transactions** | Recent M&A comps with EV/ARR and EV/EBITDA multiples |
| **Saved Searches** | Completed pipelines are auto-saved to localStorage and reloadable from the sidebar |
| **Printable Report** | One-page IC-ready report combining sector brief, companies, and comparables — export via browser print-to-PDF |

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
│  → 11-section IC memo with inline citations     │
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

## Citations

Every factual claim in the sector brief is sourced inline. The pipeline treats attribution as a first-class output, not an afterthought.

**How citations are generated**

When Google AI is available, the sector brief is generated with Google Search grounding active. Gemini retrieves real-time sources and embeds byte-offset metadata alongside the text. DealScout's post-processing layer reads those byte ranges and inserts `[SRC: url]` markers at the exact positions where the claim appears — so the footnote is anchored to the sentence, not appended at the end. If Gemini omits byte ranges (a model-version quirk), a fallback maps Gemini's own `[N]` inline footnote markers to grounding chunk URLs 1:1.

When Google AI is unavailable, the pipeline pre-fetches relevant web pages via Tavily or DuckDuckGo, injects the page excerpts into the prompt, and instructs the model to tag each claim with the source URL it drew from.

**How citations are validated**

After generation, a background pass HEAD-checks every cited URL. For each citation, the verifier:

- Follows redirects and records the final URL (Gemini sometimes cites vertexaisearch proxy URLs that resolve to the real page)
- Flags URLs that return 404 or redirect back to a homepage root — those are likely hallucinated
- Attempts a `site:` search to find a replacement if the original link is dead

The rendered sector brief separates sources into two groups: verified links (shown in the footnotes panel) and flagged links (shown in a red warning block with the raw URL so you can judge for yourself).

**Citation display in the UI**

Each `[SRC: url]` marker is converted to a compact superscript link inline in the text. The full URL list appears in a collapsible footnotes section below the brief. The model badge (e.g. `● Gemini 2.5 Flash · search`) shows which backend produced the content and whether live search was active.

---

## Verification

After the pipeline produces the sector brief, conference list, and company universe, a verification pass cross-checks the key facts that PE analysts rely on most.

**What gets verified**

| Entity | Fields checked |
|---|---|
| Sector brief | Sampled factual claims (market sizes, named companies, statistics) |
| Companies | Existence, founding year, ownership type, employee count, website reachability |
| Conferences | Existence, date and location accuracy |

**Verification paths**

Each field goes through the strongest available method:

1. **Grounding URL fetch** — if the primary research already retrieved a grounding URL for the entity, that page is fetched and used as ground truth
2. **Company website** — the company's own website is fetched as a high-confidence primary source for ownership and founding data
3. **Gemini native search** — a secondary Gemini call with Google Search grounding re-queries for the specific claim
4. **Tavily / DuckDuckGo** — dedicated search for entities where grounding context isn't available

**Verification statuses**

| Status | Meaning |
|---|---|
| `verified` | Claim explicitly confirmed by a retrieved source |
| `inferred` | Claim is consistent with available evidence — plausible but not directly sourced |
| `contradicted` | Retrieved source conflicts with the generated claim |
| `unverifiable` | No usable source was found — treat with extra caution |

The verifier is calibrated to prefer `inferred` over `unverifiable`. For well-known entities, training knowledge is a reasonable prior; `unverifiable` is reserved for cases where there is no basis to judge the claim at all.

**Auto-correction**

For `founded`, `ownership`, and `employee_count`, if the verifier finds a contradiction and has a corrected value, DealScout will automatically display the corrected figure in the company card (with the original struck through). You can override any correction via the verification badge on each pill.

**Confidence score**

Each company and conference receives an overall confidence score (High / Medium / Low) derived from the distribution of verification outcomes across its checked fields. The score is shown as a pill on each card and in the research confidence summary bar at the top of results.

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
│       ├── report.css               # Print/PDF report styles
│       └── components/
│           ├── SearchBar.jsx
│           ├── WelcomePanel.jsx     # Onboarding panel with example theses and run CTAs
│           ├── ServerWakeup.jsx     # Render cold-start detection and wakeup screen
│           ├── SectorBrief.jsx      # Markdown renderer with citation footnotes
│           ├── CompanyList.jsx
│           ├── CompanyModal.jsx     # Deep-dive profile panel
│           ├── CompanyLogo.jsx      # Company logo display
│           ├── ConferenceGrid.jsx
│           ├── ComparablesPanel.jsx
│           ├── DecisionMakers.jsx
│           ├── OutreachDraft.jsx
│           ├── ReportView.jsx       # Printable IC report view
│           ├── ReportActionBar.jsx
│           ├── ServiceMap.jsx
│           ├── LlmBadge.jsx         # LLM attribution badge
│           ├── VerificationBadge.jsx
│           ├── PipelineContext.jsx  # Multi-job state management
│           ├── SettingsContext.jsx
│           ├── SettingsDrawer.jsx   # Settings panel UI
│           └── SavedSearches.jsx
├── .env.example
└── README.md
```

---

## API reference

| Endpoint | Method | Description |
|---|---|---|
| `/api/research` | POST | Full pipeline — streams SSE log + phase results |
| `/api/research/jobs/{job_id}` | GET | Poll status and results for a running or completed job |
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
- [x] Saved searches — auto-save to localStorage, reload from sidebar
- [x] Print / PDF export — IC-ready report via browser print-to-PDF
- [ ] CRM tracker — pipeline stage tracking across saved searches
- [ ] Word export — formatted .docx one-pager per company
- [ ] Webhook / scheduled refresh — re-run saved searches on a cadence
