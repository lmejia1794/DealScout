"""
research.py — all AI calls for DealScout Phase 1.

Sequential pipeline:
  1. sector_brief   → markdown string
  2. conferences    → list[dict]
  3. companies      → list[dict]

Each step receives prior outputs as context so later steps are grounded.
Adding Phase 2 steps means appending new functions in the same pattern —
no refactoring of existing steps required.
"""

import json
import logging
import math
import os
import re
from datetime import date

import httpx
import ollama as ollama_lib
from openai import OpenAI

from search import search_for_sector_brief, search_for_conferences, search_for_companies, _extract_keywords

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a structured data assistant. "
    "When asked to return JSON, return ONLY valid JSON with no markdown fences, "
    "no preamble, and no explanation. "
    "When asked to return markdown, return only markdown."
)
TEMPERATURE = 0.2
JSON_TOKENS = 2000
BRIEF_TOKENS = 6000  # explicit large limit — avoids Ollama misinterpreting num_predict=-1

# Maximum characters of Tavily web context to inject per prompt.
# Set WEB_CTX_MAX=0 to disable the cap entirely (useful when the Ollama server
# has a large context window configured).  Any positive value truncates to that
# many chars.  Default 1200 is safe for a 2048-token context window.
WEB_CTX_MAX = int(os.getenv("WEB_CTX_MAX", "8000"))

TODAY = date.today().strftime("%B %Y")  # e.g. "April 2026"

# Whether to inject citation prompts at generation time (free — no Tavily)
_CITATIONS_ENV = os.getenv("VERIFICATION_CITATIONS_ENABLED", "true").lower() in ("1", "true", "yes")

CITATION_PROMPT_BLOCK = """
CITATIONS REQUIREMENT — mandatory, not optional:
Every specific factual claim must have an inline [SRC: ...] marker immediately after it.
This includes: every number, percentage, market size, growth rate, company name, founding year,
ownership detail, deal value, or statistic.

Citation format (pick exactly one per claim):
- Data from a URL in the search results above: [SRC: https://exact-url-from-results]
  The URL for each search result is shown in parentheses at the end of each result line —
  copy that exact URL. Do not paraphrase or shorten it.
- Training knowledge with no searchable source: [SRC: training_knowledge]
- Estimate or model inference: [SRC: estimated]
- Derived from another cited claim: [SRC: derived]

Do NOT use [SRC: model_inference].

Example:
"The DACH WFM market is valued at €2.1B [SRC: https://example.com/report-2025], growing at
8-12% annually [SRC: training_knowledge], with roughly 500 vendors [SRC: estimated]."

Cite every claim. Uncited claims are treated as unverified.
"""

# Separate block for WEB_LLM mode — Gemini has built-in search, not injected context
WEB_LLM_CITATION_BLOCK = """
CITATIONS REQUIREMENT — mandatory, not optional:
You have web search enabled and are retrieving live content from real URLs.
For EVERY factual claim append an inline [SRC: ...] marker immediately after the claim,
using the actual URL of the page you found that data on.

Citation format (pick exactly one per claim):
- URL you actually retrieved during this search: [SRC: https://full-url-you-accessed]
- Genuine training knowledge (could not find via search): [SRC: training_knowledge]
- Estimate or inference: [SRC: estimated]
- Derived from another cited value: [SRC: derived]

Do NOT write [SRC: training_knowledge] for data you found by searching — use the real URL.
Do NOT use [SRC: model_inference].

Example:
"The European logistics software market is valued at €8.2B [SRC: https://example.com/2025-report]
growing at 12% annually [SRC: https://example.com/2025-report], with over 400 vendors
[SRC: estimated]."

Every number and named statistic must be cited. Uncited claims are treated as unverified.
"""

# Regex patterns for size criteria in the thesis
_SIZE_RE = re.compile(
    r'(?P<ccy>[€$£])\s*(?P<lo>\d+(?:\.\d+)?)\s*[-–]\s*(?P<hi>\d+(?:\.\d+)?)\s*[Mm]\s*(?P<type>EV|enterprise value|ARR|revenue|recurring)',
    re.IGNORECASE,
)


def _build_size_constraints(thesis: str) -> str:
    """
    Parse size criteria from the thesis and return an explicit constraints
    block to inject into the companies prompt.

    Handles two cases:
      - EV range  → translates to implied ARR using 4–8x EV/ARR multiples
      - ARR range → used directly
    """
    lines = []
    for m in _SIZE_RE.finditer(thesis):
        ccy = m.group("ccy")
        lo = float(m.group("lo"))
        hi = float(m.group("hi"))
        kind = m.group("type").upper()

        if kind in ("EV", "ENTERPRISE VALUE"):
            # Typical B2B SaaS EV/ARR: 4–8x for mid-market
            arr_lo = math.floor(lo / 8)
            arr_hi = math.ceil(hi / 4)
            lines.append(
                f"- The thesis specifies an EV range of {ccy}{lo:.0f}–{hi:.0f}M. "
                f"At typical mid-market SaaS multiples of 4–8× ARR, this implies "
                f"target ARR of roughly {ccy}{arr_lo}–{arr_hi}M."
            )
            lines.append(
                f"- EXCLUDE companies whose ARR is clearly above {ccy}{arr_hi}M "
                f"(they would be priced well above the stated EV ceiling)."
            )
            lines.append(
                f"- Set fit_score ≤ 3 for any company whose ARR or scale implies "
                f"an EV materially outside {ccy}{lo:.0f}–{hi:.0f}M."
            )
        else:  # ARR / revenue
            lines.append(
                f"- The thesis specifies an ARR range of {ccy}{lo:.0f}–{hi:.0f}M."
            )
            lines.append(
                f"- EXCLUDE companies with ARR clearly outside this range."
            )
            lines.append(
                f"- Set fit_score ≤ 3 for companies whose revenue scale is "
                f"materially larger or smaller than {ccy}{lo:.0f}–{hi:.0f}M ARR."
            )

    if not lines:
        return ""

    return (
        "SIZE CONSTRAINTS — these are hard filters, not preferences:\n"
        + "\n".join(lines)
        + "\n\nWhen in doubt about a company's size, prefer excluding it over including it."
    )


# ---------------------------------------------------------------------------
# LLM client abstraction
# ---------------------------------------------------------------------------

def _ollama_available() -> bool:
    host = os.getenv("OLLAMA_HOST", "")
    if not host:
        return False
    try:
        httpx.get(f"{host}/api/version", timeout=3)
        return True
    except Exception:
        return False


def _web_llm_enabled() -> bool:
    return os.getenv("WEB_LLM", "").lower() in ("1", "true", "yes")


def _call_ollama(host: str, model: str, prompt: str, max_tokens: int, log_fn=None) -> str:
    """
    Call the Ollama /api/chat endpoint directly via httpx.

    We bypass the ollama Python library here because it silently drops unknown
    options (including num_ctx) in some versions, causing the model to use the
    server's default context window — which may be too small for our prompts.
    Direct HTTP gives us exact control over every parameter.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {
            "temperature": TEMPERATURE,
            "num_predict": max_tokens,
            "num_ctx": num_ctx,
        },
    }
    with httpx.Client(timeout=600) as client:
        resp = client.post(f"{host}/api/chat", json=payload)
        resp.raise_for_status()
        body = resp.json()
        done_reason = body.get("done_reason", "unknown")
        content = body["message"]["content"]
        if done_reason == "length":
            _log(
                f"WARNING: Ollama hit token limit (done_reason=length) — "
                f"response truncated at {len(content)} chars. "
                f"num_ctx={num_ctx}. Lower WEB_CTX_MAX or increase OLLAMA_NUM_CTX."
            )
        else:
            _log(f"Ollama done_reason={done_reason}, response={len(content)} chars")
        return content


def _call_openrouter(model: str, prompt: str, max_tokens: int) -> str:
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        raise RuntimeError("OPENROUTER_API_KEY not set in .env")
    oc = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=openrouter_key)
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": TEMPERATURE,
    }
    if max_tokens > 0:
        kwargs["max_tokens"] = max_tokens
    resp = oc.chat.completions.create(**kwargs)
    return resp.choices[0].message.content


def _call_llm(prompt: str, max_tokens: int, log_fn=None) -> str:
    """
    Routing logic:
      1. If WEB_LLM=true  → OpenRouter web-capable model (skips Tavily).
      2. If Ollama reachable → local Ollama.
      3. Fallback → OpenRouter standard model.
    """
    if _web_llm_enabled():
        model = os.getenv("WEB_LLM_MODEL", "google/gemini-2.0-flash-001")
        logger.info("WEB_LLM mode — using OpenRouter model: %s", model)
        return _call_openrouter(model, prompt, max_tokens)

    host = os.getenv("OLLAMA_HOST", "")
    model = os.getenv("OLLAMA_MODEL", "mixtral:8x7b-instruct-v0.1-q4_K_M")

    if _ollama_available():
        return _call_ollama(host, model, prompt, max_tokens, log_fn=log_fn)

    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if not openrouter_key:
        raise RuntimeError(
            "No AI backend configured. Please check your .env file."
        )
    if log_fn:
        log_fn("Ollama unreachable — falling back to OpenRouter")
    else:
        logger.warning("Ollama unreachable — falling back to OpenRouter")
    or_model = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
    return _call_openrouter(or_model, prompt, max_tokens)


def _strip_json_fences(text: str) -> str:
    """Strip markdown code fences (```json ... ``` or ``` ... ```) from LLM output."""
    text = text.strip()
    # Remove opening fence with optional language tag
    text = re.sub(r'^```[a-zA-Z]*\s*', '', text)
    # Remove closing fence
    text = re.sub(r'\s*```$', '', text)
    return text.strip()


def _call_json(prompt: str, log_fn=None) -> list:
    """
    Call the LLM expecting a JSON array. Retries once on parse failure.
    Returns parsed list or raises ValueError.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    raw = _call_llm(
        prompt + "\n\nReturn ONLY a raw JSON array. Do not include ```json or any other text.",
        JSON_TOKENS,
        log_fn=log_fn,
    )
    try:
        parsed = json.loads(_strip_json_fences(raw))
        return parsed
    except json.JSONDecodeError:
        _log("JSON parse failed on first attempt — retrying with stricter prompt")
        retry_prompt = (
            prompt
            + "\n\nYour previous response was not valid JSON. "
            "Return ONLY the raw JSON array with absolutely no other text."
        )
        raw2 = _call_llm(retry_prompt, JSON_TOKENS, log_fn=log_fn)
        return json.loads(_strip_json_fences(raw2))


# ---------------------------------------------------------------------------
# Step 1 — Sector Brief
# ---------------------------------------------------------------------------

def generate_sector_brief(thesis: str, log_fn=None, extra_context: str = "", citations_enabled: bool = False) -> str:
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    if _web_llm_enabled():
        _log(f"WEB_LLM mode — skipping Tavily, using {os.getenv('WEB_LLM_MODEL', 'google/gemini-2.0-flash-001')} with built-in search")
        web_section = "Use your web search capability to find current data on this sector."
    else:
        _log("Running Tavily searches for sector brief...")
        web_context = search_for_sector_brief(thesis)
        _log(f"Sector searches complete — {len(web_context.splitlines())} lines of context, {len(web_context)} chars")
        if extra_context:
            web_context = web_context + "\n\n" + extra_context
            _log(f"Injected scraped source context ({len(extra_context)} chars)")
        if WEB_CTX_MAX > 0 and len(web_context) > WEB_CTX_MAX:
            web_context = web_context[:WEB_CTX_MAX]
            _log(f"Web context truncated to {WEB_CTX_MAX} chars (set WEB_CTX_MAX=0 to disable cap)")
        web_section = f"Web search results:\n{web_context}"
    _log(f"Sending sector brief prompt (num_predict={BRIEF_TOKENS})...")

    if citations_enabled:
        citation_block = WEB_LLM_CITATION_BLOCK if _web_llm_enabled() else CITATION_PROMPT_BLOCK
    else:
        citation_block = ""

    prompt = f"""You are a senior private equity analyst at a European lower-middle-market B2B software fund (€20–150M EV deal range, Europe-only mandate). Write a structured sector brief for internal investment committee use. Be specific, data-driven, and Europe-focused. Every claim should be actionable for a deal team. Aim for 3–5 substantive, data-backed sentences per section — avoid generic statements.

Investment thesis: {thesis}

{web_section}
{citation_block}

Produce a sector brief with exactly these sections in this order:

## Market Definition & Scope
Define the category precisely — what is explicitly included and excluded. Note adjacent categories the fund should be aware of but is not targeting (e.g. "excludes broader ERP but includes WFM modules that operate independently"). Flag if this is a discrete market or a sub-segment of something larger. Note whether the market is primarily horizontal or vertical.

## Market Size & Growth (Europe)
European figures only — do not cite global TAM without a European breakdown. Segment by key geographies (DACH, Nordics, Benelux, UK, Southern Europe, CEE) where the market behaves differently in terms of penetration or vendor concentration. Provide a specific CAGR and the 2–3 primary drivers behind it. Note current cloud vs. on-premise split and migration trajectory.

## Demand Drivers & Tailwinds
What is causing companies to buy this software now that was not true 5 years ago. Be specific: name relevant regulations (e.g. EU Working Time Directive, GDPR implications, eInvoicing mandates), identify the specific industries or buyer personas driving adoption, and describe what legacy system is being replaced. These points become the investment narrative.

## Sub-sector Breakdown
Identify 3–5 distinct product niches within the sector. For each: brief description, relative market size or importance, and whether it contains PE-relevant targets at the right size and ownership profile. Call out which niches are most fragmented and therefore most interesting for buy-and-build.

## Competitive Landscape
Structure in three tiers:
**Tier 1 — Large strategics (>€100M ARR or part of a large group):** Name them. These are not acquisition targets but set the product standard and are the most likely exit buyers. Note which are actively acquiring.
**Tier 2 — Mid-market independents (€10–100M ARR):** Name key companies, note known PE or VC backing where relevant. This is the target universe — characterise the cohort size and ownership mix.
**Tier 3 — Micro-vendors and point solutions (<€10M ARR):** Characterise the long tail. Note roll-up potential.

## M&A & PE Activity
List notable acquisitions in the last 3 years — include acquirer, target, year, and reported deal value or multiple where available. Name the most active PE buyers and strategic acquirers in the space. State the typical EV/ARR or EV/EBITDA range observed in recent transactions. Flag any known assets currently in process or rumoured to be coming to market.

## Ideal Acquisition Target
Be concrete — this is what the deal team uses to qualify companies. Cover:
- Revenue model: ARR % vs services mix (preference: >70% recurring)
- Customer profile: company size served, industry vertical, churn and NRR characteristics
- Geography: HQ country and customer base distribution — is the business still largely domestic or has it begun internationalising?
- Ownership situation: which ownership types are most common and most actionable (founder-led, family-owned, PE secondary approaching end of hold)
- Size window: ARR range, implied EV at typical sector multiples, employee count
- Growth and EBITDA margin profile typical of fundable businesses in this sector

## Value Creation Levers
How does a PE owner create value post-acquisition in this specific sector. Be concrete:
- Internationalisation: which geographies are the natural next markets and why (language proximity, regulatory similarity, existing customer demand)
- Product extension: adjacent modules or integrations that expand wallet share
- Buy-and-build: what types of bolt-on companies exist at sub-€10M ARR and what do they add
- Pricing and packaging: is there evidence of under-monetisation relative to value delivered
- Operational levers: margin improvement opportunities typical in this sector

## Exit Landscape
Who are the realistic buyers at exit and at what multiples:
- Strategic acquirers: name the most likely ones and cite their acquisition history in this sector (company acquired, year, multiple if known)
- Financial buyers: name larger PE funds actively doing roll-ups in this space
- Recent comparable exits: target name, acquirer, year, reported EV/ARR or EV/EBITDA multiple
- IPO viability: realistic or not for a €50–150M EV company in this sector, and why

## Red Flags & Watch-outs
Risks specific to this sector that would cause a deal team to pass or price conservatively:
- Customer concentration thresholds typical in the sector
- Commoditisation pressure or open-source disruption risk (be specific about which product areas)
- AI displacement risk: which parts of the product workflow are most exposed to AI substitution in the next 3–5 years
- Regulatory risk: any upcoming EU legislation that could disrupt the market
- Signs the market is over-capitalised or that multiples are compressing

## Key Questions for Management
List 6–8 specific questions a deal team would ask in a first management call. These must be sector-specific and probe something that would materially affect the investment decision if the answer were unfavourable. Format as a numbered list. Bad examples (too generic): "What is your churn rate?", "Describe your competitive differentiation." Good examples (sector-specific): "What % of your customers are on multi-year contracts and what is your gross retention on renewal?", "Which countries currently generate >5% of your ARR and what is driving cross-border expansion?", "How many of your top-20 customers use only your core module vs. 2+ modules?"

Use ## for each section heading exactly as shown above. Write in clear, direct language suitable for an investment committee memo. If you do not have a specific figure, say so explicitly — do not fabricate numbers.

IMPORTANT: Return ONLY plain markdown text. Do NOT return JSON, do NOT wrap the output in a JSON object or array, do NOT use code fences."""
    _log(f"Prompt size: {len(prompt)} chars (~{len(prompt)//4} tokens estimated)")
    result = _call_llm(prompt, BRIEF_TOKENS, log_fn=log_fn)

    # Guard: if the model returned JSON instead of markdown, extract the text values
    stripped = result.strip()
    if stripped.startswith('{'):
        try:
            import json as _json
            parsed = _json.loads(_strip_json_fences(stripped))
            # Flatten nested dict to markdown sections
            top = parsed.get('sector_brief', parsed)
            if isinstance(top, dict):
                sections = []
                for heading, body in top.items():
                    if isinstance(body, str):
                        sections.append(f"## {heading}\n\n{body}")
                    elif isinstance(body, list):
                        items = "\n".join(
                            f"- {item.get('niche', item.get('name', str(item)))}: {item.get('description', '')}"
                            if isinstance(item, dict) else f"- {item}"
                            for item in body
                        )
                        sections.append(f"## {heading}\n\n{items}")
                if sections:
                    result = "\n\n".join(sections)
                    _log("WARNING: model returned JSON — converted to markdown")
        except Exception:
            pass  # leave result as-is, normalize() in frontend will handle it

    _log(f"Sector brief complete ({len(result)} chars, ~{len(result)//4} tokens)")
    return result


# ---------------------------------------------------------------------------
# Step 2 — Conferences
# ---------------------------------------------------------------------------

def generate_conferences(thesis: str, sector_brief: str, log_fn=None, extra_context: str = "") -> tuple:
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    _raw_conferences_context = ""
    if _web_llm_enabled():
        _log(f"WEB_LLM mode — skipping Tavily search for conferences")
        web_section = "Use your web search capability to find real upcoming conferences."
    else:
        _log("Running Tavily searches for conferences...")
        web_context = search_for_conferences(thesis)
        _raw_conferences_context = web_context  # preserve for verification reuse
        _log(f"Conference searches complete — {len(web_context.splitlines())} lines of context, {len(web_context)} chars")
        if extra_context:
            web_context = web_context + "\n\n" + extra_context
        if WEB_CTX_MAX > 0 and len(web_context) > WEB_CTX_MAX:
            web_context = web_context[:WEB_CTX_MAX]
            _log(f"Web context truncated to {WEB_CTX_MAX} chars (set WEB_CTX_MAX=0 to disable cap)")
        web_section = f"Web search results:\n{web_context}"
    _log("Calling LLM for conference list...")

    prompt = f"""Investment thesis: {thesis}

Sector brief context:
{sector_brief}

{web_section}

Today's date is {TODAY}. Identify 5–8 real upcoming conferences relevant to this investment thesis.
Only include events that have NOT yet occurred as of {TODAY}.
Return a JSON array where each object has exactly these keys:
- name (string)
- date (string, e.g. "June 3–5, 2026"; append [SRC: url] if found in search results)
- location (string, city and country; append [SRC: url] if found in search results)
- description (string, 1–2 sentences)
- website (string or null)
- estimated_cost (string — always provide a best-guess cost range even if uncertain, e.g. "€800–1,500" or "€1,500–3,000" or "Free"; only write "Unknown" if it is a brand-new or highly obscure event with no comparable; do NOT append [SRC: ...] to this field)
- notable_attendees (array of strings — company or org names known to attend)
- relevance (string, 1 sentence explaining relevance to the thesis)

For date and location: only append [SRC: url] when you found that specific fact in the search results. Do not invent URLs."""
    result = _call_json(prompt, log_fn=log_fn)
    _log(f"Conference list complete ({len(result)} items)")
    return result, _raw_conferences_context


# ---------------------------------------------------------------------------
# Step 3 — Company Universe
# ---------------------------------------------------------------------------

def generate_companies(thesis: str, sector_brief: str, known_companies: list = None, log_fn=None, extra_context: str = "") -> tuple:
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    known_companies = known_companies or []

    _raw_companies_context = ""
    if _web_llm_enabled():
        _log(f"WEB_LLM mode — skipping Tavily search for companies")
        web_section = f"""Use your web search capability to find real companies matching this thesis.

Thesis: "{thesis}"

BEFORE you search, understand the target profile so you search efficiently:
- European headquarters only (non-European HQ = instant disqualification, do not include)
- Founder-led, family-owned, or early PE-backed (approaching end of hold) — NOT controlled by large strategic buyers
- Sub-€200M EV — this means typically <€30M ARR for a SaaS company at market multiples
- Independent company — not a subsidiary, division, or product line of a larger group

DO NOT search for or include companies you already know fail these criteria. Skip immediately:
- Any company acquired by a large strategic (e.g. WiseTech/CargoWise, E2open/BluJay, Oracle, SAP, Descartes)
- Any US/Australian/Asian-headquartered company
- Any company with >1,000 employees or ARR clearly above €50M
- Any publicly listed company

Search strategy — run targeted searches for companies that PASS the above criteria:
1. Search by country + product type: "freight forwarding software Netherlands", "3PL TMS Germany founder-led", "logistics ERP Nordics independent"
2. Search ecosystem directories: Microsoft AppSource logistics ISVs Europe, Dynamics 365 freight forwarding partners
3. Search for "Mittelstand" logistics software companies, regional freight management software
4. Search specifically for small/mid-market vendors not covered in mainstream logistics tech press

The goal is to find 8–12 companies that genuinely qualify — well-known within their niche but NOT the large platforms."""
    else:
        _log("Running Tavily searches for company universe...")
        web_context = search_for_companies(thesis)
        _raw_companies_context = web_context  # preserve for verification reuse
        _log(f"Company searches complete — {len(web_context.splitlines())} lines of context, {len(web_context)} chars")
        if extra_context:
            web_context = web_context + "\n\n" + extra_context
        if WEB_CTX_MAX > 0 and len(web_context) > WEB_CTX_MAX:
            web_context = web_context[:WEB_CTX_MAX]
            _log(f"Web context truncated to {WEB_CTX_MAX} chars (set WEB_CTX_MAX=0 to disable cap)")
        web_section = f"Web search results:\n{web_context}"

    size_constraints = _build_size_constraints(thesis)
    if size_constraints:
        _log(f"Extracted size constraints from thesis — injecting into prompt")
    if known_companies:
        _log(f"Anchor companies injected: {', '.join(known_companies)}")
    _log("Calling LLM for company universe...")

    anchor_block = ""
    if known_companies:
        names = ", ".join(f'"{c}"' for c in known_companies)
        anchor_block = f"""
ANCHOR COMPANIES — must include:
The following companies have been pre-identified as strong potential fits. You MUST include ALL of them in your results, fully scored and described. Do not omit them regardless of what your searches return: {names}
"""

    prompt = f"""Investment thesis: {thesis}

{size_constraints + chr(10) if size_constraints else ""}Sector brief context:
{sector_brief}

{web_section}

Identify 8–12 specific, real European companies that match this investment thesis.{anchor_block}
GEOGRAPHY — hard filter:
- Only include companies whose REGISTERED LEGAL HEADQUARTERS is in a European country.
- A European office or European customers do not qualify — the HQ must be in Europe.
- If you are uncertain whether a company's HQ is in Europe, exclude it.

ACQUIRABILITY — hard filter, exclude all of the following:
- Companies already acquired by a large strategic buyer or major PE firm with a long hold horizon (e.g. acquired by Blackstone, Thoma Bravo, SAP, Oracle, etc.) — these are not available for acquisition.
- Publicly listed companies (require a public-to-private transaction — different process, different mandate).
- Subsidiaries or divisions of larger groups.
- Only include: founder-led/family-owned independents, VC-backed companies reaching profitability, or PE-backed companies where the fund is approaching end of hold period (typically 4–7 years since investment).

SIZE discipline:
- EV (enterprise value) is NOT the same as ARR. A company with €50M ARR at 6× multiple has ~€300M EV.
- If the thesis states an EV range, work backwards: EV ÷ 8 to EV ÷ 4 gives the plausible ARR range for mid-market SaaS.
- Do not include large well-known vendors — prefer lesser-known companies that genuinely fit the size window.

NAMES — always use the company's official Latin/Roman alphabet name as shown on their website or in international press. Never render names in Cyrillic, Arabic, Bengali, Chinese, or any other non-Latin script.

Return a JSON array where each object has exactly these keys:
- name (string)
- country (string — European country of legal HQ)
- hq_city (string or null — city of headquarters)
- founded (string or null — founding year as a string, e.g. "2015"; append [SRC: url] if found in search results, e.g. "2015 [SRC: https://company.com/about]")
- estimated_arr (string or null — ARR estimate, e.g. "€10–20M"; append [SRC: url] if found in search results)
- employee_count (string or null — headcount range, e.g. "50–200"; append [SRC: url] if found in search results)
- ownership (string — one of: "Founder-led", "Family-owned", "VC-backed", "PE-backed (name fund if known)", "PE-backed (fund unknown)", "Public (exchange)", "Acquired (acquirer name, year if known)", "Unknown"; append [SRC: url] if found in search results)
- description (string, 2–3 sentences including ownership context)
- website (string or null)
- fit_score (integer 1–10 — penalise heavily for size mismatch, non-European HQ, or already acquired)
- fit_rationale (string, 1–2 sentences — note any ownership or geography concerns)
- signals (array of strings — growth signals, recent news, partnerships, funding rounds)

For founded, estimated_arr, employee_count, ownership: only append [SRC: url] when you found that specific fact in the search results above. Do not invent URLs.

Sort the array by fit_score descending before returning."""
    result = _call_json(prompt, log_fn=log_fn)
    _log(f"Company universe complete ({len(result)} companies)")
    return result, _raw_companies_context


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def run_research(thesis: str, known_companies: list = None, settings: dict = None, log_fn=None) -> dict:
    """
    Full Phase 1 pipeline. Returns dict matching ResearchResponse shape.
    Phase 2 steps (deep profiles, outreach, CRM, comps) can be appended here
    without touching existing steps.
    """
    from scraper import get_source_context

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    settings = settings or {}
    scraping_enabled = settings.get("source_scraping_enabled", True)

    # Step 0 — Source Discovery (best-effort, never blocks pipeline)
    if scraping_enabled and not _web_llm_enabled():
        _log("=== Step 0: Source Discovery ===")
        source_context = get_source_context(thesis, log_fn=log_fn)
    else:
        if _web_llm_enabled():
            _log("Step 0: Source Discovery skipped (WEB_LLM mode — model has built-in search)")
        else:
            _log("Step 0: Source Discovery skipped (disabled in settings)")
        source_context = ""

    citations_enabled = settings.get("verification_citations_enabled", _CITATIONS_ENV)

    _log("=== Phase 1: Sector Brief ===")
    sector_brief = generate_sector_brief(thesis, log_fn=log_fn, extra_context=source_context, citations_enabled=citations_enabled)

    _log("=== Phase 2: Conferences ===")
    conferences_context = ""
    try:
        conferences, conferences_context = generate_conferences(thesis, sector_brief, log_fn=log_fn, extra_context=source_context)
    except (ValueError, json.JSONDecodeError) as e:
        _log(f"ERROR: Conference generation failed — {e}")
        conferences = []

    _log("=== Phase 3: Company Universe ===")
    companies_context = ""
    try:
        companies, companies_context = generate_companies(thesis, sector_brief, known_companies=known_companies, log_fn=log_fn, extra_context=source_context)
        companies.sort(key=lambda c: c.get("fit_score", 0), reverse=True)
    except (ValueError, json.JSONDecodeError) as e:
        _log(f"ERROR: Company generation failed — {e}")
        companies = []

    _log("=== Research complete ===")
    raw_result = {
        "sector_brief": sector_brief,
        "conferences": conferences,
        "companies": companies,
    }

    # Verification pass
    verification_enabled = settings.get("verification_enabled", True)
    if verification_enabled:
        from verification import verify_research, _wrap_unverified
        try:
            return verify_research(
                raw_result,
                settings=settings,
                log_fn=log_fn,
                companies_context=companies_context,
                conferences_context=conferences_context,
            )
        except Exception as e:
            _log(f"WARNING: Verification pass failed — {e}. Returning unverified result.")
            from verification import _wrap_unverified
            return _wrap_unverified(raw_result)
    else:
        from verification import _wrap_unverified
        return _wrap_unverified(raw_result)
