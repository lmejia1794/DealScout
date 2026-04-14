"""
verification.py — Post-generation AI evaluation & verification pass for DealScout.

Two layers:
  1. Citation extraction: parses [SRC: ...] markers from LLM output (free)
  2. Tavily re-verification: one search + one LLM call per entity (batch approach)

Gated by env flags:
  VERIFICATION_TAVILY_ENABLED    — set false to skip Tavily (saves credits)
  VERIFICATION_CITATIONS_ENABLED — set false to skip citation prompts (free)
  VERIFICATION_TAVILY_MAX_CALLS  — hard credit cap per run (0 = unlimited, default 20)
"""

import json
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TAVILY_ENABLED = os.getenv("VERIFICATION_TAVILY_ENABLED", "true").lower() in ("1", "true", "yes")
CITATIONS_ENABLED = os.getenv("VERIFICATION_CITATIONS_ENABLED", "true").lower() in ("1", "true", "yes")
TAVILY_MAX_CALLS = int(os.getenv("VERIFICATION_TAVILY_MAX_CALLS", "20"))
CITATION_FETCH_MAX_CHARS = int(os.getenv("CITATION_FETCH_MAX_CHARS", "3000"))

CITATION_RE = re.compile(r'\[SRC:\s*([^\]]+)\]')

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Citation extraction (free — no network calls)
# ---------------------------------------------------------------------------

def _extract_citations(text: str):
    """
    Extract all [SRC: ...] markers from text.
    Returns (cleaned_text, citations_list).

    Each citation dict:
        claim_snippet  — text immediately before the marker (up to 80 chars)
        citation_raw   — raw content of [SRC: ...]
        citation_type  — "url" | "training_knowledge" | "estimated" | "derived"
        citation_url   — https://... or None
    """
    citations = []
    idx_counter = [0]

    def _handle_match(m):
        source = m.group(1).strip()
        start = max(0, m.start() - 100)
        preceding = text[start:m.start()].strip()
        snippet = preceding
        for sep in ('. ', '! ', '? ', '\n'):
            pos = snippet.rfind(sep)
            if pos >= 0:
                snippet = snippet[pos + len(sep):]
        claim_snippet = snippet[:80].strip() or f"claim_{idx_counter[0]}"
        idx_counter[0] += 1

        src_lower = source.lower()
        if src_lower == 'estimated':
            ctype, curl = 'estimated', None
        elif src_lower == 'derived':
            ctype, curl = 'derived', None
        elif src_lower in ('training_knowledge', 'model_inference'):
            ctype, curl = 'training_knowledge', None
        elif source.startswith('http://') or source.startswith('https://'):
            ctype, curl = 'url', source
        else:
            ctype, curl = 'training_knowledge', None

        citations.append({
            'claim_snippet': claim_snippet,
            'citation_raw': source,
            'citation_type': ctype,
            'citation_url': curl,
        })
        return ''

    cleaned = CITATION_RE.sub(_handle_match, text)
    return cleaned.strip(), citations


def _clean_entity_fields(entity: dict) -> dict:
    """Strip all [SRC: ...] markers from entity string field values for clean display."""
    return {
        k: CITATION_RE.sub('', str(v)).strip() if isinstance(v, str) else v
        for k, v in entity.items()
    }


def _extract_field_citation(field_value: str):
    """
    Extract a single [SRC: ...] from a structured field value.
    Returns (clean_value, citation_type, citation_url).
    """
    m = CITATION_RE.search(str(field_value))
    if not m:
        return str(field_value), 'training_knowledge', None
    source = m.group(1).strip()
    clean_value = CITATION_RE.sub('', str(field_value)).strip()
    src_lower = source.lower()
    if src_lower == 'estimated':
        return clean_value, 'estimated', None
    elif src_lower == 'derived':
        return clean_value, 'derived', None
    elif src_lower in ('training_knowledge', 'model_inference'):
        return clean_value, 'training_knowledge', None
    elif source.startswith('http://') or source.startswith('https://'):
        return clean_value, 'url', source
    return clean_value, 'training_knowledge', None


def _validate_citation_url(url: str) -> bool:
    """HEAD request to confirm URL exists. Returns True if status < 400."""
    try:
        r = httpx.head(url, timeout=5, follow_redirects=True)
        return r.status_code < 400
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Website discovery (Tavily search when URL is missing)
# ---------------------------------------------------------------------------

def _find_website(name: str, location: str = "", log_fn=None, is_conference: bool = False) -> Optional[str]:
    """
    Search for the official website of a company or conference when none is known.
    Returns the first plausible homepage URL or None.
    """
    from search import _run_search, _get_client

    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    try:
        client = _get_client()
        if is_conference:
            query = f'"{name}" conference official website'
        else:
            query = f'"{name}" {location} official website homepage'.strip()
        results = _run_search(client, query)
        for r in results:
            url = r.get('url', '')
            # Accept the first result that looks like a homepage (short path, right domain)
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                path = parsed.path.rstrip('/')
                # Prefer root or very short paths — likely a homepage
                if parsed.scheme in ('http', 'https') and len(path) <= 20:
                    _log(f"  _find_website: found {url} for '{name}'")
                    return url
            except Exception:
                continue
        # Fallback: return first result URL if any
        if results:
            return results[0].get('url')
    except Exception as e:
        _log(f"  _find_website failed for '{name}': {e}")
    return None


# ---------------------------------------------------------------------------
# Website liveness check (free HEAD request — no Tavily)
# ---------------------------------------------------------------------------

def _check_website_live(url: str, log_fn=None) -> dict:
    """
    HEAD-check a company website. Detects broken URLs and domain redirects
    that may indicate a rebrand (e.g. CargoApps → impargo.com).

    If the full path fails (e.g. soloplan.com/en returns 404), automatically
    retries the root domain (soloplan.com) before marking as broken.
    """
    def _log(msg):
        if log_fn:
            log_fn(msg)

    if not url:
        return {'status': 'unverifiable', 'citation_note': 'No website URL provided'}

    def _head(target: str):
        return httpx.head(target, timeout=8, follow_redirects=True)

    def _extract_domain(u: str) -> str:
        return u.split('/')[2].lstrip('www.') if '//' in u else ''

    def _root_url(u: str) -> Optional[str]:
        """Return scheme+domain only, or None if already at root."""
        try:
            parts = u.split('/')
            # parts: ['https:', '', 'domain.com', 'path', ...]
            if len(parts) <= 3 or (len(parts) == 4 and parts[3] == ''):
                return None  # already at root
            return f"{parts[0]}//{parts[2]}"
        except Exception:
            return None

    try:
        resp = _head(url)
        final_url = str(resp.url)
        original_domain = _extract_domain(url)
        final_domain = _extract_domain(final_url)

        if resp.status_code < 400:
            if original_domain and final_domain and original_domain != final_domain:
                return {
                    'status': 'inferred',
                    'source_url': final_url,
                    'source_snippet': f'Website redirects to {final_domain} — possible rebrand or domain change',
                    'citation_note': f'Original URL {url} now points to {final_url}',
                }
            return {'status': 'verified', 'source_url': final_url, 'source_snippet': 'Website is live and reachable'}

        # Sub-path failed — retry root domain before giving up
        root = _root_url(url)
        if root:
            _log(f"    {url} returned {resp.status_code} — retrying root: {root}")
            try:
                root_resp = _head(root)
                root_final = str(root_resp.url)
                root_domain = _extract_domain(root_final)
                if root_resp.status_code < 400:
                    return {
                        'status': 'verified',
                        'source_url': root_final,
                        'source_snippet': f'Website live at {root_domain} (sub-path {url} returned {resp.status_code})',
                    }
            except Exception:
                pass

        return {
            'status': 'contradicted',
            'citation_note': f'Website returned HTTP {resp.status_code} — may be broken or company no longer exists',
        }

    except Exception as e:
        return {'status': 'unverifiable', 'citation_note': f'Could not reach website: {type(e).__name__}'}


# ---------------------------------------------------------------------------
# Citation URL fetcher + secondary verification
# ---------------------------------------------------------------------------

def _fetch_and_verify_citation(
    url: str,
    claim: str,
    entity_name: str,
    log_fn=None,
) -> dict:
    """
    Fetch the cited URL, extract readable text, ask a second LLM call to
    confirm whether the claim is actually supported by the page content.
    Returns a Verification-compatible dict with citation_url and source_url set.
    """
    from research import _call_llm, _strip_json_fences
    from bs4 import BeautifulSoup

    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    # Sub-step A: fetch page
    try:
        resp = httpx.get(url, timeout=10, follow_redirects=True,
                         headers={"User-Agent": _BROWSER_UA})
        final_url = str(resp.url)
        if resp.status_code == 404:
            _log(f"  Citation URL 404: {url}")
            return {
                'status': 'unverifiable',
                'citation_url': url,
                'source_url': url,
                'citation_note': 'Cited URL returned 404 — likely hallucinated URL',
                'claim': claim,
            }
        if resp.status_code >= 400:
            return {
                'status': 'unverifiable',
                'citation_url': url,
                'source_url': url,
                'citation_note': f'Could not fetch cited URL: HTTP {resp.status_code}',
                'claim': claim,
            }

        # Detect homepage-redirect: original URL had a specific path but resolved
        # to the root — the specific page doesn't exist (hallucinated URL pattern)
        try:
            from urllib.parse import urlparse as _urlparse
            orig = _urlparse(url)
            final = _urlparse(final_url)
            orig_path = orig.path.rstrip('/')
            final_path = final.path.rstrip('/')
            orig_domain = orig.netloc.lower().lstrip('www.')
            final_domain = final.netloc.lower().lstrip('www.')
            # Same domain but original had a deep path that collapsed to root/homepage
            if (orig_path and orig_path != '/'
                    and (final_path in ('', '/') or final_path == orig_path[:3])
                    and orig_domain == final_domain):
                _log(f"  Citation URL redirects to homepage — likely hallucinated: {url} → {final_url}")
                return {
                    'status': 'unverifiable',
                    'citation_url': url,
                    'source_url': final_url,
                    'citation_note': 'Cited URL redirects to homepage — specific page does not exist (likely hallucinated URL)',
                    'claim': claim,
                }
        except Exception:
            pass

    except httpx.TimeoutException:
        return {
            'status': 'unverifiable',
            'citation_url': url,
            'source_url': url,
            'citation_note': 'Could not fetch cited URL: timeout',
            'claim': claim,
        }
    except Exception as e:
        return {
            'status': 'unverifiable',
            'citation_url': url,
            'source_url': url,
            'citation_note': f'Could not fetch cited URL: {type(e).__name__}',
            'claim': claim,
        }

    # Sub-step B: extract readable text (same logic as scraper.py)
    page_text = ""
    try:
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        content = (
            soup.find("article") or soup.find("main")
            or soup.find(attrs={"role": "main"})
            or soup.find(class_="content") or soup.find(id="content")
            or soup.body
        )
        if content:
            raw = content.get_text(separator=" ", strip=True)
            page_text = re.sub(r"\s{2,}", " ", raw)[:CITATION_FETCH_MAX_CHARS]
    except Exception:
        pass

    if not page_text:
        return {
            'status': 'unverifiable',
            'citation_url': url,
            'source_url': final_url,
            'citation_note': 'Cited URL fetched but no readable content found',
            'claim': claim,
        }

    # Sub-step C: secondary LLM verification call
    try:
        prompt = f"""You are a fact-checker reading a web page to verify a specific claim.

Claim to verify: "{claim}"
About: {entity_name}

Web page content (from {final_url}):
{page_text}

Does this page content support, contradict, or not address the claim?

Return ONLY a JSON object:
{{
  "verdict": "verified" | "contradicted" | "unverifiable",
  "supporting_excerpt": "direct quote from the page supporting your verdict, max 100 chars, or null",
  "corrected_value": "if contradicted, the correct value from the page, or null"
}}"""

        raw = _call_llm(prompt, max_tokens=300)
        parsed = json.loads(_strip_json_fences(raw))
        verdict = parsed.get('verdict', 'unverifiable')
        if verdict not in ('verified', 'contradicted', 'unverifiable'):
            verdict = 'unverifiable'

        _log(f"  Citation verify: {verdict} — {final_url}")
        return {
            'status': verdict,
            'citation_url': url,
            'source_url': final_url,
            'source_snippet': parsed.get('supporting_excerpt'),
            'corrected_value': parsed.get('corrected_value') if verdict == 'contradicted' else None,
            'claim': claim,
        }
    except Exception as e:
        _log(f"  Secondary LLM call failed: {e}")
        return {
            'status': 'unverifiable',
            'citation_url': url,
            'source_url': final_url,
            'citation_note': f'Verification call failed: {type(e).__name__}',
            'claim': claim,
        }


def _verify_field_with_citations(
    field_name: str,
    claim: str,
    citation_url: Optional[str],
    citation_type: str,
    entity_name: str,
    log_fn=None,
    use_tavily: Optional[bool] = None,
    existing_context: str = "",
    call_state: Optional[dict] = None,
) -> dict:
    """
    Citation-first priority logic:
      estimated / derived    → inferred immediately, no network calls
      training_knowledge     → Tavily fallback (if budget allows)
      url                    → fetch + verify; Tavily fallback if fetch fails
    """
    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    enabled = TAVILY_ENABLED if use_tavily is None else use_tavily

    if citation_type in ('estimated', 'derived'):
        _log(f"  {field_name}: {citation_type} → inferred immediately")
        return {'status': 'inferred', 'claim': claim, 'citation_note': citation_type}

    budget_ok = (
        enabled and (
            call_state is None
            or TAVILY_MAX_CALLS == 0
            or call_state.get('count', 0) < TAVILY_MAX_CALLS
        )
    )

    if citation_type == 'training_knowledge':
        if budget_ok:
            _log(f"  {field_name}: training_knowledge → Tavily fallback")
            batch = _verify_entity_batch(
                entity_name=entity_name,
                search_query=f'"{entity_name}" {claim[:60]}',
                claims={field_name: claim},
                log_fn=log_fn,
                use_tavily=True,
                existing_context=existing_context,
                call_state=call_state,
            )
            return batch.get(field_name, {'status': 'unverifiable', 'claim': claim})
        return {
            'status': 'unverifiable',
            'citation_note': 'From model training knowledge — no source available',
            'claim': claim,
        }

    if citation_type == 'url' and citation_url:
        result = _fetch_and_verify_citation(citation_url, claim, entity_name, log_fn=log_fn)
        if result.get('status') == 'unverifiable' and budget_ok:
            _log(f"  {field_name}: citation fetch failed → Tavily fallback")
            batch = _verify_entity_batch(
                entity_name=entity_name,
                search_query=f'"{entity_name}" {claim[:60]}',
                claims={field_name: claim},
                log_fn=log_fn,
                use_tavily=True,
                existing_context=existing_context,
                call_state=call_state,
            )
            return batch.get(field_name, result)
        return result

    return {'status': 'pending', 'claim': claim}


# ---------------------------------------------------------------------------
# Batch entity verification (1 Tavily call + 1 LLM call per entity)
# ---------------------------------------------------------------------------

def _verify_entity_batch(
    entity_name: str,
    search_query: str,
    claims: dict,           # {field_name: claim_string}
    log_fn=None,
    use_tavily: Optional[bool] = None,
    existing_context: str = "",
    call_state: Optional[dict] = None,  # {"count": int} — shared mutable counter
) -> dict:
    """
    One Tavily search (or reuse existing context) + one LLM call for all claims.
    Returns {field_name: Verification-compatible dict}.
    """
    from search import _run_search, _get_client
    from research import _call_llm, _strip_json_fences

    def _log(msg):
        logger.debug(msg)
        if log_fn:
            log_fn(msg)

    enabled = TAVILY_ENABLED if use_tavily is None else use_tavily

    if not enabled:
        return {k: {'status': 'pending', 'claim': v} for k, v in claims.items()}

    # Check call cap
    if call_state is not None and TAVILY_MAX_CALLS > 0:
        if call_state.get('count', 0) >= TAVILY_MAX_CALLS:
            _log(f"  Tavily cap reached ({TAVILY_MAX_CALLS}) — skipping {entity_name}")
            return {k: {'status': 'pending', 'citation_note': 'Tavily call limit reached for this run', 'claim': v} for k, v in claims.items()}

    # Reuse existing context if it covers this entity (free — no Tavily call)
    tavily_context = ""
    used_cache = False
    if existing_context and entity_name.lower() in existing_context.lower():
        # Entity appeared in initial research context — use it directly
        tavily_context = existing_context[:3000]
        used_cache = True
        _log(f"  Using cached research context for {entity_name}")
    else:
        # Fresh Tavily search
        try:
            client = _get_client()
            results = _run_search(client, search_query)
            if call_state is not None:
                call_state['count'] = call_state.get('count', 0) + 1
            if results:
                ctx_parts = [f"URL: {r.get('url', '')}\n{r.get('content', '')[:400]}" for r in results[:5]]
                tavily_context = "\n\n".join(ctx_parts)
            _log(f"  Tavily search #{call_state.get('count', '?') if call_state else '?'}: {search_query}")
        except Exception as e:
            _log(f"  Tavily search failed: {e}")
            return {k: {'status': 'unverifiable', 'checked_query': search_query} for k in claims}

    if not tavily_context:
        return {k: {'status': 'unverifiable', 'checked_query': search_query} for k in claims}

    # One LLM call for all claims
    try:
        claims_json = json.dumps(claims, indent=2)
        prompt = f"""You are a fact-checker. Given these web search results about {entity_name}, assess each claim below as "verified", "contradicted", or "unverifiable".

Search results:
{tavily_context}

Claims to assess:
{claims_json}

Return ONLY a JSON object where each key matches a claim key and the value is:
{{
  "verdict": "verified" | "contradicted" | "unverifiable",
  "source_url": "most relevant URL or null",
  "snippet": "brief supporting excerpt or null",
  "corrected_value": "the correct scalar value from sources if contradicted (e.g. '2008', 'Acquired by SAP in 2021', 'October 14-16, 2026'), or null if not contradicted"
}}

verdict must be exactly one of: "verified", "contradicted", "unverifiable".
corrected_value should be short and direct — it will be displayed inline as a replacement."""

        raw = _call_llm(prompt, max_tokens=400)
        raw = _strip_json_fences(raw)
        parsed = json.loads(raw)

        results_out = {}
        for field, claim_text in claims.items():
            field_result = parsed.get(field, {})
            verdict = field_result.get('verdict', 'unverifiable')
            if verdict not in ('verified', 'contradicted', 'unverifiable'):
                verdict = 'unverifiable'
            corrected = field_result.get('corrected_value') if verdict == 'contradicted' else None
            results_out[field] = {
                'status': verdict,
                'source_url': field_result.get('source_url'),
                'source_snippet': field_result.get('snippet'),
                'checked_query': None if used_cache else search_query,
                'claim': claim_text,
                'corrected_value': corrected,
            }
        return results_out
    except Exception as e:
        _log(f"  Batch LLM call failed: {e}")
        return {k: {'status': 'unverifiable', 'checked_query': search_query, 'claim': v} for k, v in claims.items()}


# ---------------------------------------------------------------------------
# Company verification
# ---------------------------------------------------------------------------

def verify_company(
    company: dict,
    log_fn=None,
    use_tavily: Optional[bool] = None,
    existing_context: str = "",
    call_state: Optional[dict] = None,
) -> dict:
    """
    Verify 3 high-stakes fields + website liveness check.
    Returns a VerifiedCompany-compatible dict.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    name = company.get('name', '?')
    country = company.get('country', '')
    _log(f"> Verifying: {name} ({country})")

    verifications = {}

    # Website: check if live; if missing, search for it
    if company.get('website'):
        wv = _check_website_live(company['website'], log_fn=log_fn)
        verifications['website'] = wv
        snippet = wv.get('source_snippet') or wv.get('citation_note', '')
        _log(f"    website: {wv['status']} — {snippet[:80]}")
    else:
        found_url = _find_website(name, country, log_fn=log_fn)
        if found_url:
            company['website'] = found_url
            verifications['website'] = {'status': 'verified', 'source_url': found_url,
                                        'source_snippet': f'Website found via search: {found_url}'}
            _log(f"    website: found via search → {found_url}")

    # ARR and headcount: always inferred — private company data is rarely public
    # Extract citations from raw values for claim text, but still mark inferred
    raw_arr = str(company.get('estimated_arr') or '')
    if raw_arr and raw_arr != 'None':
        clean_arr, _, _ = _extract_field_citation(raw_arr)
        verifications['estimated_arr'] = {
            'status': 'inferred',
            'source_snippet': 'ARR estimates for private companies are rarely publicly available — treat as model inference',
            'claim': f'{name} has estimated ARR of {clean_arr}',
        }

    raw_emp = str(company.get('employee_count') or '')
    if raw_emp and raw_emp != 'None':
        clean_emp, _, _ = _extract_field_citation(raw_emp)
        verifications['employee_count'] = {
            'status': 'inferred',
            'source_snippet': 'Headcount estimates for private companies are rarely publicly available — treat as model inference',
            'claim': f'{name} has approximately {clean_emp} employees',
        }

    # For each verifiable field: extract citation first, use citation-first if URL available
    batch_claims = {}

    # existence: no inline citation expected — always Tavily batch
    batch_claims['existence'] = f'{name} is a software company based in {country}'

    # ownership: citation-first if URL provided by LLM
    raw_ownership = str(company.get('ownership') or '')
    if raw_ownership and raw_ownership != 'None':
        clean_ownership, ctype, curl = _extract_field_citation(raw_ownership)
        claim = f'{name} ownership: {clean_ownership}'
        if ctype == 'url' and curl:
            _log(f"    ownership: citation URL found → fetching {curl}")
            verifications['ownership'] = _verify_field_with_citations(
                'ownership', claim, curl, ctype, name, log_fn, use_tavily, existing_context, call_state)
            icon = '✓' if verifications['ownership'].get('status') == 'verified' else '~'
            _log(f"    ownership: {verifications['ownership'].get('status')} {icon}")
        else:
            batch_claims['ownership'] = claim

    # founded: citation-first if URL provided by LLM
    raw_founded = str(company.get('founded') or '')
    if raw_founded and raw_founded != 'None':
        clean_founded, ctype, curl = _extract_field_citation(raw_founded)
        claim = f'{name} was founded in {clean_founded}'
        if ctype == 'url' and curl:
            _log(f"    founded: citation URL found → fetching {curl}")
            verifications['founded'] = _verify_field_with_citations(
                'founded', claim, curl, ctype, name, log_fn, use_tavily, existing_context, call_state)
            icon = '✓' if verifications['founded'].get('status') == 'verified' else '~'
            _log(f"    founded: {verifications['founded'].get('status')} {icon}")
        else:
            batch_claims['founded'] = claim

    # Clean company for output — strip all [SRC: ...] markers AFTER citation extraction
    company = _clean_entity_fields(company)

    # Batch remaining fields via Tavily (existence always here, others if no citation URL)
    if batch_claims:
        search_query = f'"{name}" {country} software company'
        batch = _verify_entity_batch(
            entity_name=name,
            search_query=search_query,
            claims=batch_claims,
            log_fn=log_fn,
            use_tavily=use_tavily,
            existing_context=existing_context,
            call_state=call_state,
        )
        for field, v in batch.items():
            verifications[field] = v
            icon = '✓' if v['status'] == 'verified' else ('✗' if v['status'] == 'contradicted' else '~')
            _log(f"    {field}: {v['status']} {icon}")

    overall = _derive_confidence(verifications)
    _log(f"    Overall confidence: {overall}")
    return {
        'company': company,
        'verifications': verifications,
        'overall_confidence': overall,
    }


# ---------------------------------------------------------------------------
# Conference verification
# ---------------------------------------------------------------------------

def verify_conference(
    conference: dict,
    log_fn=None,
    use_tavily: Optional[bool] = None,
    existing_context: str = "",
    call_state: Optional[dict] = None,
) -> dict:
    """
    Verify 2 high-stakes fields (date+location, existence).
    estimated_cost is marked inferred directly — rarely publicly listed.
    Returns a VerifiedConference-compatible dict.
    """
    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    name = conference.get('name', '?')

    # Extract citations from date/location BEFORE cleaning
    raw_date = str(conference.get('date') or '')
    raw_location = str(conference.get('location') or '')
    clean_date, date_ctype, date_curl = _extract_field_citation(raw_date)
    clean_location, loc_ctype, loc_curl = _extract_field_citation(raw_location)
    # Pick the best available URL for date_location claim
    dl_citation_url = date_curl or loc_curl
    dl_citation_type = 'url' if dl_citation_url else 'training_knowledge'

    year_m = re.search(r'\d{4}', clean_date)
    year = year_m.group(0) if year_m else ''

    _log(f"> Verifying conference: {name}")

    verifications = {}

    # Website: if missing, search for the conference homepage
    if not conference.get('website'):
        found_url = _find_website(name, clean_location or '', log_fn=log_fn, is_conference=True)
        if found_url:
            conference['website'] = found_url
            _log(f"    website: found via search → {found_url}")

    # Mark cost as inferred — ticket prices are rarely searchable
    raw_cost = str(conference.get('estimated_cost') or '')
    if raw_cost and raw_cost != 'None':
        clean_cost, _, _ = _extract_field_citation(raw_cost)
        verifications['estimated_cost'] = {
            'status': 'inferred',
            'source_snippet': 'Conference ticket prices are rarely available in web search results — treat as estimate',
            'claim': f'Attendance costs {clean_cost}',
        }

    batch_claims = {}

    # date_location: citation-first if a URL was embedded in date or location
    if clean_date or clean_location:
        dl_claim = f'{name} is taking place in {clean_date} in {clean_location}'
        if dl_citation_type == 'url' and dl_citation_url:
            _log(f"    date_location: citation URL found → fetching {dl_citation_url}")
            verifications['date_location'] = _verify_field_with_citations(
                'date_location', dl_claim, dl_citation_url, dl_citation_type,
                name, log_fn, use_tavily, existing_context, call_state)
            icon = '✓' if verifications['date_location'].get('status') == 'verified' else '~'
            _log(f"    date_location: {verifications['date_location'].get('status')} {icon}")
        else:
            batch_claims['date_location'] = dl_claim

    # existence: always Tavily batch
    batch_claims['existence'] = f'{name} is a real conference happening in {year or "2026"}'

    # Clean conference for output AFTER citation extraction
    conference = _clean_entity_fields(conference)

    if batch_claims:
        search_query = f'"{name}" {year} conference'
        batch = _verify_entity_batch(
            entity_name=name,
            search_query=search_query,
            claims=batch_claims,
            log_fn=log_fn,
            use_tavily=use_tavily,
            existing_context=existing_context,
            call_state=call_state,
        )
        for field, v in batch.items():
            verifications[field] = v
            icon = '✓' if v['status'] == 'verified' else ('✗' if v['status'] == 'contradicted' else '~')
            _log(f"    {field}: {v['status']} {icon}")

    # date_location contradicted → always low confidence
    if verifications.get('date_location', {}).get('status') == 'contradicted':
        overall = 'low'
    elif verifications.get('existence', {}).get('status') == 'contradicted':
        overall = 'low'
    else:
        overall = _derive_confidence(verifications)
    _log(f"    Overall confidence: {overall}")

    return {
        'conference': conference,
        'verifications': verifications,
        'overall_confidence': overall,
    }


# ---------------------------------------------------------------------------
# Sector brief verification
# ---------------------------------------------------------------------------

def verify_sector_brief(
    sector_brief: str,
    log_fn=None,
    use_tavily: Optional[bool] = None,
    call_state: Optional[dict] = None,
) -> dict:
    """
    Citation-first verification for the sector brief.

    Priority:
      1. URL citations → fetch page, secondary LLM call to confirm claim (free of Tavily)
      2. estimated / derived → mark inferred immediately
      3. training_knowledge → mark unverifiable (too many in a sector brief to burn Tavily budget)
      4. No URL citations found → fall back to numeric claim extraction + Tavily batch
    """
    from research import _call_llm, _strip_json_fences

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    _log("=== Sector Brief Verification ===")

    # Extract all [SRC: ...] citations from the brief text
    _, citations = _extract_citations(sector_brief)
    url_citations = [c for c in citations if c['citation_type'] == 'url']
    _log(f"> Found {len(citations)} citations, {len(url_citations)} with real URLs")

    verified_claims = []

    if url_citations:
        # --- Citation-first path ---
        for cit in url_citations:
            claim_text = cit['claim_snippet']
            _log(f">   Verifying: {claim_text[:70]}")
            _log(f">   Citation URL: {cit['citation_url']}")
            result = _fetch_and_verify_citation(
                url=cit['citation_url'],
                claim=claim_text,
                entity_name='sector brief',
                log_fn=log_fn,
            )
            icon = '✓' if result.get('status') == 'verified' else ('✗' if result.get('status') == 'contradicted' else '?')
            _log(f">   {result.get('status')} {icon} (source: {result.get('source_url', '')})")
            verified_claims.append({'claim': claim_text, 'verification': result})

        # Mark estimated / derived as inferred
        for cit in citations:
            if cit['citation_type'] in ('estimated', 'derived'):
                verified_claims.append({
                    'claim': cit['claim_snippet'],
                    'verification': {
                        'status': 'inferred',
                        'claim': cit['claim_snippet'],
                        'citation_note': cit['citation_type'],
                    }
                })

    else:
        # --- Fallback: no URL citations → extract numeric claims + Tavily batch ---
        _log("> No URL citations — falling back to numeric claim extraction + Tavily")

        extract_prompt = f"""Extract the 3 most specific, verifiable numeric claims from this sector brief.
Focus on: market size figures, growth rates, percentages — NOT qualitative statements.
Return ONLY a JSON object with keys "claim_1", "claim_2", "claim_3" (use null if fewer than 3 exist).

Sector brief:
{sector_brief}"""

        try:
            raw = _call_llm(extract_prompt, max_tokens=200)
            raw = _strip_json_fences(raw)
            extracted = json.loads(raw)
            if not isinstance(extracted, dict):
                extracted = {}
            claims = {k: v for k, v in extracted.items() if isinstance(v, str) and v.strip()}
        except Exception as e:
            _log(f"  Claim extraction failed: {e}")
            return {'claims': [], 'overall_confidence': None}

        if not claims:
            _log("> No numeric claims extracted — skipping verification")
            return {'claims': [], 'overall_confidence': None}

        _log(f"> Extracted {len(claims)} numeric claims — verifying in 1 Tavily batch call")

        batch = _verify_entity_batch(
            entity_name="this sector",
            search_query=f"sector market size growth rate {list(claims.values())[0][:50]}",
            claims=claims,
            log_fn=log_fn,
            use_tavily=use_tavily,
            call_state=call_state,
        )

        for key, claim_text in claims.items():
            v = batch.get(key, {'status': 'unverifiable'})
            icon = '✓' if v['status'] == 'verified' else ('✗' if v['status'] == 'contradicted' else '?')
            _log(f'> {key}: "{claim_text[:60]}..." → {v["status"]} {icon}')
            verified_claims.append({'claim': claim_text, 'verification': v})

    if not verified_claims:
        return {'claims': [], 'overall_confidence': None}

    overall = _derive_confidence({str(i): c['verification'] for i, c in enumerate(verified_claims)})
    return {'claims': verified_claims, 'overall_confidence': overall}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def verify_field(
    entity_name: str,
    field_name: str,
    claim: str,
    context: str = "",
    use_tavily: Optional[bool] = None,
    log_fn=None,
) -> dict:
    """
    On-demand verification of a single field. Used by the /api/verify/field endpoint.
    Returns (verification_dict, tavily_was_used).

    Strategy:
    1. If context provided: try Gemini-only first (no Tavily credit).
    2. If Gemini-only returns verified/contradicted: return immediately.
    3. Otherwise: fall back to _verify_entity_batch with Tavily.
    """
    from research import _call_llm, _strip_json_fences

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    enabled = TAVILY_ENABLED if use_tavily is None else use_tavily

    # Step 1: Try context-only (free)
    if context and context.strip():
        try:
            prompt = f"""You are a fact-checker. Given these search results, assess whether this claim is supported, contradicted, or cannot be determined.

Claim: {claim}

Search results:
{context[:3000]}

Return ONLY a JSON object:
{{
  "verdict": "verified" | "contradicted" | "unverifiable",
  "source_url": "most relevant URL or null",
  "snippet": "brief supporting excerpt or null"
}}"""
            raw = _call_llm(prompt, max_tokens=200)
            parsed = json.loads(_strip_json_fences(raw))
            verdict = parsed.get('verdict', 'unverifiable')
            if verdict in ('verified', 'contradicted'):
                _log(f"  verify_field: context-only result = {verdict} (no Tavily used)")
                corrected = parsed.get('corrected_value') if verdict == 'contradicted' else None
                return {
                    'status': verdict,
                    'source_url': parsed.get('source_url'),
                    'source_snippet': parsed.get('snippet'),
                    'claim': claim,
                    'corrected_value': corrected,
                }, False
        except Exception as e:
            _log(f"  verify_field: context-only attempt failed — {e}")

    # Step 2: Tavily batch (1 call)
    if not enabled:
        return {'status': 'pending', 'citation_note': 'Tavily verification is disabled in settings', 'claim': claim}, False

    batch = _verify_entity_batch(
        entity_name=entity_name,
        search_query=f'"{entity_name}" {claim[:60]}',
        claims={field_name: claim},
        log_fn=log_fn,
        use_tavily=True,
        existing_context="",   # force fresh search
        call_state=None,
    )
    v = batch.get(field_name, {'status': 'unverifiable', 'claim': claim})
    return v, True


def _derive_confidence(verifications: dict) -> str:
    statuses = [v.get('status') for v in verifications.values()]
    if any(s == 'contradicted' for s in statuses):
        return 'low'
    if sum(1 for s in statuses if s == 'verified') >= 3:
        return 'high'
    return 'medium'


def _wrap_unverified(research_result: dict) -> dict:
    """Wrap raw result in verified shape with all statuses pending."""
    return {
        'sector_brief': research_result['sector_brief'],
        'sector_brief_verification': {'claims': [], 'overall_confidence': None},
        'conferences': [
            {'conference': _clean_entity_fields(c), 'verifications': {}, 'overall_confidence': None}
            for c in research_result.get('conferences', [])
        ],
        'companies': [
            {'company': _clean_entity_fields(c), 'verifications': {}, 'overall_confidence': None}
            for c in research_result.get('companies', [])
        ],
        '_companies_context': '',
        '_conferences_context': '',
    }


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------

def verify_research(
    research_result: dict,
    settings: Optional[dict] = None,
    log_fn=None,
    companies_context: str = "",
    conferences_context: str = "",
) -> dict:
    """
    Takes raw run_research() output and returns VerifiedResearchResponse shape.
    Accepts pre-gathered Tavily context to minimize additional credit usage.
    """
    _settings = settings or {}
    use_tavily_setting = _settings.get('verification_tavily_enabled', None)
    use_tavily = TAVILY_ENABLED if use_tavily_setting is None else bool(use_tavily_setting)

    def _log(msg):
        logger.info(msg)
        if log_fn:
            log_fn(msg)

    n_companies = len(research_result.get('companies', []))
    n_confs = len(research_result.get('conferences', []))
    cap_str = f", cap={TAVILY_MAX_CALLS}" if TAVILY_MAX_CALLS > 0 else ""
    _log(f"=== Verification Pass ===")
    _log(f"  Tavily: {'enabled' if use_tavily else 'disabled'}{cap_str} | ~{n_companies + n_confs + 1} calls max")

    # Shared mutable Tavily call counter
    call_state = {'count': 0}

    _log(f"--- Verifying sector brief... (1/3) ---")
    sector_verification = verify_sector_brief(
        research_result['sector_brief'],
        log_fn=log_fn,
        use_tavily=use_tavily,
        call_state=call_state,
    )

    _log(f"--- Verifying {n_confs} conferences... (2/3) ---")
    verified_conferences = []
    for conf in research_result.get('conferences', []):
        verified_conferences.append(verify_conference(
            conf,
            log_fn=log_fn,
            use_tavily=use_tavily,
            existing_context=conferences_context,
            call_state=call_state,
        ))

    _log(f"--- Verifying {n_companies} companies... (3/3) ---")
    verified_companies = []
    for i, company in enumerate(research_result.get('companies', [])):
        _log(f"  Company {i + 1}/{n_companies}: {company.get('name', '?')}")
        verified_companies.append(verify_company(
            company,
            log_fn=log_fn,
            use_tavily=use_tavily,
            existing_context=companies_context,
            call_state=call_state,
        ))

    _log(f"=== Verification complete — {call_state['count']} Tavily calls used ===")

    return {
        'sector_brief': research_result['sector_brief'],
        'sector_brief_verification': sector_verification,
        'conferences': verified_conferences,
        'companies': verified_companies,
        '_companies_context': companies_context,
        '_conferences_context': conferences_context,
    }
