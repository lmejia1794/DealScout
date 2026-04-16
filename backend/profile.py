"""
profile.py — Phase 2 AI calls for DealScout.

Endpoints served via main.py:
  POST /api/company/profile   → SSE stream → CompanyProfile
  POST /api/company/outreach  → JSON        → OutreachResponse
"""

import json
import logging
import os
import re
from typing import Optional

import httpx

from search import _get_client, format_results, _run_search
from research import (
    _call_llm,
    _call_json,
    _strip_json_fences,
    _escape_control_chars,
    _google_available,
    WEB_CTX_MAX,
    TODAY,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: JSON object (dict) variant of _call_json
# ---------------------------------------------------------------------------

def _call_json_object(prompt: str, log_fn=None) -> dict:
    """Like _call_json but expects a JSON object (dict), not an array."""
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    raw = _call_llm(
        prompt + "\n\nReturn ONLY a raw JSON object. Do not include ```json or any other text.",
        2000,
        log_fn=log_fn,
    )
    def _parse(s):
        cleaned = _escape_control_chars(_strip_json_fences(s))
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            try:
                from json_repair import repair_json
                repaired = repair_json(cleaned, return_objects=True)
                if isinstance(repaired, dict):
                    _log("JSON repaired from truncated output")
                    return repaired
            except Exception:
                pass
            raise

    try:
        return _parse(raw)
    except json.JSONDecodeError:
        _log("JSON parse failed on first attempt — retrying with stricter prompt")
        retry_prompt = (
            prompt
            + "\n\nYour previous response was not valid JSON. "
            "Return ONLY the raw JSON object with absolutely no other text."
        )
        raw2 = _call_llm(retry_prompt, 2000, log_fn=log_fn)
        return _parse(raw2)


# ---------------------------------------------------------------------------
# Decision maker enrichment (LinkedIn + email)
# ---------------------------------------------------------------------------

def _linkedin_url_from_results(results: list) -> Optional[str]:
    """Extract the first linkedin.com/in/ URL from Tavily search results."""
    for r in results:
        url = r.get("url", "")
        if re.search(r"linkedin\.com/in/[^/?#]+", url):
            return url.split("?")[0]  # strip tracking params
    return None


def _hunter_email(domain: str, name: str, log_fn=None) -> Optional[str]:
    """
    Look up a professional email via Hunter.io API.
    Requires HUNTER_API_KEY env var. Returns None if not configured or not found.
    """
    api_key = os.getenv("HUNTER_API_KEY", "")
    if not api_key:
        return None
    parts = name.strip().split()
    if len(parts) < 2:
        return None
    first, last = parts[0], parts[-1]
    try:
        resp = httpx.get(
            "https://api.hunter.io/v2/email-finder",
            params={"domain": domain, "first_name": first, "last_name": last, "api_key": api_key},
            timeout=10,
        )
        data = resp.json()
        email = data.get("data", {}).get("email")
        if email:
            if log_fn:
                log_fn(f"Hunter.io found email for {name}: {email}")
            return email
    except Exception as e:
        if log_fn:
            log_fn(f"Hunter.io lookup failed for {name}: {e}")
    return None


def _enrich_decision_makers(
    company_name: str,
    website: Optional[str],
    decision_makers: list,
    log_fn=None,
) -> list:
    """
    Enrich each decision maker with a verified LinkedIn URL (via Tavily) and
    optionally an email address (via Hunter.io if HUNTER_API_KEY is set).
    Runs one Tavily query per person — skipped silently if Tavily is unavailable.
    """
    if not decision_makers:
        return decision_makers

    # Extract domain from website for Hunter.io
    domain = None
    if website:
        m = re.search(r"https?://(?:www\.)?([^/]+)", website)
        if m:
            domain = m.group(1)

    try:
        client = _get_client()
    except Exception:
        return decision_makers  # Tavily not configured — skip enrichment

    enriched = []
    for dm in decision_makers:
        name = dm.get("name", "")
        dm_copy = dict(dm)

        if name:
            # LinkedIn search
            results = _run_search(client, f'site:linkedin.com/in "{name}" "{company_name}"')
            linkedin_url = _linkedin_url_from_results(results)
            if linkedin_url:
                dm_copy["linkedin_url"] = linkedin_url
                if log_fn:
                    log_fn(f"LinkedIn found for {name}")
            else:
                if log_fn:
                    log_fn(f"LinkedIn not found for {name}")

            # Email lookup (Hunter.io)
            if domain:
                email = _hunter_email(domain, name, log_fn=log_fn)
                if email:
                    dm_copy["email"] = email

        enriched.append(dm_copy)

    return enriched


# ---------------------------------------------------------------------------
# Profile generation
# ---------------------------------------------------------------------------

def generate_profile(company: dict, thesis: str, log_fn=None, settings: dict = None) -> dict:
    """
    Generate a CompanyProfile for a single company.
    Returns a dict matching CompanyProfile shape.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    _log("=== Profile Generation ===")

    # Step 1 — Tavily searches
    if _google_available():
        _log("WEB_LLM mode — skipping Tavily searches for profile")
        web_context = ""
    else:
        _log("Running Tavily searches...")
        client = _get_client()
        name = company.get("name", "")
        country = company.get("country", "")
        queries = [
            f"{name} {country}",
            f"{name} CEO founder leadership team",
            f"{name} customers markets offices expansion",
        ]
        blocks = [format_results(_run_search(client, q), q) for q in queries]
        web_context = "\n\n".join(blocks)
        _log(f"Searches complete — {len(web_context.splitlines())} lines of context, {len(web_context)} chars")
        if WEB_CTX_MAX > 0 and len(web_context) > WEB_CTX_MAX:
            web_context = web_context[:WEB_CTX_MAX]
            _log(f"Web context truncated to {WEB_CTX_MAX} chars")

    # Build company summary from Phase 1 data
    company_summary = f"""Company: {company.get('name')}
Country / HQ: {company.get('hq_city', '')}, {company.get('country', '')}
Ownership: {company.get('ownership', 'Unknown')}
Founded: {company.get('founded', 'Unknown')}
Estimated ARR: {company.get('estimated_arr', 'Unknown')}
Employees: {company.get('employee_count', 'Unknown')}
Website: {company.get('website', 'N/A')}
Description: {company.get('description', '')}
Fit rationale: {company.get('fit_rationale', '')}
Growth signals: {', '.join(company.get('signals', []))}"""

    web_section = (
        "Use your web search capability to research this company."
        if _google_available()
        else f"Web search results:\n{web_context}"
    )

    # Step 2 — Profile generation
    _log("Generating company profile...")
    profile_prompt = f"""You are a senior private equity analyst at a European B2B tech fund.

Investment thesis: {thesis}

Company data from initial screening:
{company_summary}

{web_section}

Today's date: {TODAY}

Return ONLY a raw JSON object with exactly these keys:
- business_model (string, markdown — 2-4 sentences on revenue model, pricing, delivery)
- financials (string, markdown — ARR estimate, growth rate, margins where known; note uncertainty)
- recent_news (string, markdown — last 12-24 months of notable events, funding, partnerships, launches)
- competitive_positioning (string, markdown — key differentiators vs alternatives, moat)
- fit_assessment (string, markdown — how well this company fits the investment thesis, specific reasons)
- hq_country (string — full English country name of legal HQ, e.g. "Germany")
- service_countries (array of strings — full English country names where company has customers, offices, or known market presence; always include hq_country)

Do not include decision_makers — that comes in a separate call."""

    profile_data = _call_json_object(profile_prompt, log_fn=log_fn)
    _log("Profile complete")

    # Step 3 — Decision makers (separate call, reuses same web context)
    _log("Identifying decision makers...")
    dm_prompt = f"""Company: {company.get('name')}, {company.get('country')}
Website: {company.get('website', 'N/A')}

{web_section}

Identify 2–4 key decision makers at this company relevant to a PE acquisition approach
(CEO, founder, CFO, or equivalent).

Return ONLY a JSON array where each object has exactly these keys:
- name (string)
- title (string)
- notes (string or null — 1 sentence on their background or relevance)

Do NOT include linkedin_url — omit that field entirely."""

    try:
        decision_makers = _call_json(dm_prompt, log_fn=log_fn)
        _log(f"Found {len(decision_makers)} decision makers")
    except (ValueError, json.JSONDecodeError) as e:
        _log(f"Decision maker identification failed — {e}")
        decision_makers = []

    # Step 4 — LinkedIn profile search (Tavily-based, best-effort)
    if not _google_available():
        _log("Searching for LinkedIn profiles...")
        decision_makers = _enrich_decision_makers(
            company_name=company.get("name", ""),
            website=company.get("website"),
            decision_makers=decision_makers,
            log_fn=log_fn,
        )

    # Step 5 — Contact enrichment (email + phone) — all DMs in parallel
    _settings = settings or {}
    enrichment_enabled = _settings.get("contact_enrichment_enabled", True)
    if enrichment_enabled:
        from enrichment import enrich_contact
        from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
        _log(f"=== Contact Enrichment ({len(decision_makers)} decision makers in parallel) ===")

        def _enrich_one(dm):
            name = dm.get("name", "?")
            _log(f"  Enriching: {name} ({dm.get('title', '')})")
            try:
                return dm, enrich_contact(
                    name=name,
                    title=dm.get("title", ""),
                    company_name=company.get("name", ""),
                    company_website=company.get("website"),
                    company_country=company.get("country"),
                    log_fn=log_fn,
                )
            except Exception as e:
                _log(f"  Enrichment failed for {name}: {e}")
                return dm, {"enrichment_notes": f"Enrichment error: {e}"}

        contacts: dict = {}
        with ThreadPoolExecutor(max_workers=len(decision_makers) or 1) as pool:
            futures = {pool.submit(_enrich_one, dm): dm for dm in decision_makers}
            try:
                for future in as_completed(futures, timeout=75):
                    try:
                        dm, contact = future.result()
                        contacts[id(dm)] = (dm, contact)
                    except Exception as e:
                        dm = futures[future]
                        _log(f"  Enrichment error for {dm.get('name', '?')}: {e}")
                        contacts[id(dm)] = (dm, {"enrichment_notes": f"Enrichment error: {e}"})
            except FuturesTimeout:
                _log("  Contact enrichment timeout — returning partial results")
                # Mark any unfinished DMs gracefully instead of crashing
                for dm in decision_makers:
                    if id(dm) not in contacts:
                        contacts[id(dm)] = (dm, {"enrichment_notes": "Enrichment timed out"})

        for dm in decision_makers:
            _, contact = contacts.get(id(dm), (dm, {"enrichment_notes": "No result"}))
            dm["contact"] = contact
    else:
        _log("Contact enrichment disabled in settings — skipping")

    profile_data["decision_makers"] = decision_makers
    return profile_data


# ---------------------------------------------------------------------------
# Outreach generation
# ---------------------------------------------------------------------------

VOLPI_CONTEXT = """
About Volpi Capital:
Volpi Capital is a London-based private equity firm that partners exclusively with founder-led and
family-owned European B2B technology and tech-enabled services companies. Volpi's typical investment
is a majority stake in companies with €5–50M ARR, and provides:
- Patient, long-term capital with no fixed fund lifecycle pressure
- Active operational support: a dedicated operating team embedded with portfolio companies
- International expansion: deep network across European markets to accelerate cross-border growth
- M&A expertise: buy-and-build capability to consolidate fragmented verticals
- Founder-friendly: designed to work alongside existing management; founders often retain equity
  and continue to lead post-investment
Volpi does NOT replace founders — it amplifies them. The typical hold period is 5–7 years,
with alignment on building durable, cash-generative businesses rather than quick flips.
""".strip()


def generate_outreach(company: dict, profile: dict, thesis: str) -> dict:
    """
    Generate a cold outreach email. Returns dict with 'subject' and 'body'.
    No Tavily search — uses profile data already fetched.
    """
    signals = company.get("signals", [])
    signals_str = "; ".join(signals[:3]) if signals else "growth-stage B2B software"
    fit = profile.get("fit_assessment", "")[:400]

    prompt = f"""You are writing a cold outreach email on behalf of Volpi Capital.

{VOLPI_CONTEXT}

Target company: {company.get('name')}, {company.get('country')}
Ownership: {company.get('ownership', 'Unknown')}
Recent signals: {signals_str}
Business model: {profile.get('business_model', '')[:300]}
Fit assessment: {fit}
Investment thesis: {thesis}

Write a cold outreach email. Rules:
- 200 words max (not 150 — more detail is needed to convey the Volpi value proposition)
- Open with a specific, informed observation about the company (a signal, market position, or product detail)
- Explain why Volpi is relevant to them specifically: reference their ownership type, growth stage,
  and at least one concrete thing Volpi could provide (e.g. international expansion, M&A support,
  operational resource, patient capital)
- Make clear Volpi is founder-friendly and does not replace management
- The ask is a 20-minute exploratory call — low commitment
- No hollow flattery, no generic "I came across your company" opener
- No sign-off or sender name

Return ONLY a raw JSON object:
{{"subject": "...", "body": "..."}}"""

    raw = _call_llm(prompt, 600)
    try:
        cleaned = _escape_control_chars(_strip_json_fences(raw))
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            from json_repair import repair_json
            result = repair_json(cleaned, return_objects=True)
            if not isinstance(result, dict):
                raise ValueError(f"json_repair returned non-dict: {type(result)}")
        return {"subject": result.get("subject", ""), "body": result.get("body", "")}
    except Exception:
        return {
            "subject": f"Introduction — {company.get('name')}",
            "body": "Sorry, the email draft could not be generated. Please try again.",
        }
